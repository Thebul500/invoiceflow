"""LLM-based invoice data extraction using Ollama.

Reads PDF text (via pypdf), email (.eml) bodies/attachments, or raw text input
and sends it to the Ollama API with a structured prompt to extract invoice
fields as JSON.
"""

import base64
import email as email_stdlib
import hashlib
import json
import logging
from email.policy import default as email_default_policy
from pathlib import Path

import httpx
from pypdf import PdfReader

from ..config import settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are an invoice data extraction assistant. Extract the following fields
from the invoice text below and return ONLY valid JSON (no markdown, no explanation).

Required JSON structure:
{
  "invoice_number": "string or null",
  "vendor_name": "string or null",
  "vendor_address": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "subtotal": number or null,
  "tax_amount": number or null,
  "total_amount": number or null,
  "currency": "USD",
  "po_number": "string or null",
  "line_items": [
    {
      "description": "string",
      "quantity": number,
      "unit_price": number or null,
      "amount": number
    }
  ]
}

Invoice text:
"""


def extract_text_from_pdf(file_path: str) -> str:
    """Extract all text from a PDF file using pypdf."""
    reader = PdfReader(file_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file for dedup."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _is_image(file_path: str) -> bool:
    suffix = Path(file_path).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}


async def extract_with_ollama(text: str, image_b64: str | None = None) -> dict:
    """Send text (and optionally an image) to Ollama and parse the JSON response."""
    prompt = EXTRACTION_PROMPT + text

    payload: dict = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if image_b64:
        payload["images"] = [image_b64]

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()

    raw_response = result.get("response", "")
    return _parse_llm_json(raw_response)


def _parse_llm_json(text: str) -> dict:  # type: ignore[type-arg]
    """Parse JSON from LLM response, handling markdown code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                logger.debug("Substring JSON parse also failed")
        logger.warning("Failed to parse LLM JSON response: %s", cleaned[:200])
        return {}


def parse_email(file_path: str) -> tuple[str, list[tuple[str, bytes]]]:
    """Parse an .eml file and extract body text and attachments.

    Returns (body_text, [(filename, data), ...]).
    """
    raw = Path(file_path).read_bytes()
    msg = email_stdlib.message_from_bytes(raw, policy=email_default_policy)

    body_parts: list[str] = []
    attachments: list[tuple[str, bytes]] = []

    # Extract headers as context
    for header in ("From", "To", "Subject", "Date"):
        val = msg.get(header)
        if val:
            body_parts.append(f"{header}: {val}")

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in disposition:
            fname = part.get_filename() or "attachment"
            raw_payload = part.get_payload(decode=True)
            if isinstance(raw_payload, bytes):
                attachments.append((fname, raw_payload))
        elif content_type == "text/plain":
            raw_payload = part.get_payload(decode=True)
            if isinstance(raw_payload, bytes):
                body_parts.append(raw_payload.decode(errors="replace"))

    return "\n".join(body_parts), attachments


async def extract_invoice_data(file_path: str) -> dict:
    """Full extraction pipeline: read file → extract text → LLM extraction.

    Returns dict with extracted fields plus raw_text and file_hash.
    """
    path = Path(file_path)
    file_hash = compute_file_hash(file_path)

    image_b64 = None
    if path.suffix.lower() == ".pdf":
        raw_text = extract_text_from_pdf(file_path)
    elif _is_image(file_path):
        raw_text = ""
        with open(file_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()
    elif path.suffix.lower() in {".eml", ".msg"}:
        raw_text, attachments = parse_email(file_path)
        # If email has PDF/image attachments, process the first one
        for att_name, att_data in attachments:
            att_ext = Path(att_name).suffix.lower()
            if att_ext == ".pdf":
                # Save attachment temporarily and extract text
                att_path = Path(settings.upload_dir) / att_name
                att_path.write_bytes(att_data)
                raw_text += "\n" + extract_text_from_pdf(str(att_path))
                break
            elif att_ext in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}:
                image_b64 = base64.b64encode(att_data).decode()
                break
    else:
        raw_text = path.read_text(errors="replace")

    extracted = await extract_with_ollama(raw_text, image_b64)
    extracted["raw_text"] = raw_text
    extracted["file_hash"] = file_hash
    return extracted
