"""Invoice processing pipeline — orchestrates the full data ingestion and processing workflow.

This is the central pipeline that ties all engine components together:
1. Data ingestion: Read files from disk, fetch from URLs, scan watch directories
2. Text extraction: PDF parsing, image OCR via LLM, email body/attachment extraction
3. LLM extraction: Send content to Ollama for structured field extraction
4. Validation: Compare against purchase orders, flag discrepancies
5. Duplicate detection: Fuzzy matching against existing invoices
6. Categorization: Assign expense categories based on vendor/line items
7. Export: Generate CSV or QuickBooks IIF output

Supports batch processing of entire directories and individual file processing.
"""

import json
import logging
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..models import Invoice, LineItem
from .categorizer import categorize_invoice
from .duplicates import check_duplicates
from .exporter import export_csv, export_iif
from .extractor import compute_file_hash, extract_invoice_data
from .ingestor import SUPPORTED_EXTENSIONS
from .validator import validate_against_po

logger = logging.getLogger(__name__)


async def process_invoice(file_path: str, db: AsyncSession) -> dict:
    """Process a single invoice file through the full pipeline.

    Pipeline stages:
    1. Read and validate the input file
    2. Extract text/image content (PDF, image, email, plaintext)
    3. Send to Ollama LLM for structured data extraction
    4. Store in database with line items
    5. Categorize expense type
    6. Check for duplicate invoices (fuzzy matching)
    7. Validate against purchase order if PO number present

    Args:
        file_path: Path to the invoice file on disk.
        db: Async database session.

    Returns:
        Dict with invoice data and processing results.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file type is unsupported.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Invoice file not found: {file_path}")

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {path.suffix}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    logger.info("Pipeline: processing %s", path.name)

    # Stage 1-3: Extract structured data via LLM
    try:
        extracted = await extract_invoice_data(str(path))
    except Exception as e:
        logger.error("Pipeline: extraction failed for %s: %s", path.name, e)
        extracted = {
            "raw_text": "",
            "file_hash": compute_file_hash(str(path)),
        }

    line_items_data = extracted.pop("line_items", [])
    raw_text = extracted.pop("raw_text", "")
    file_hash = extracted.pop("file_hash", "")

    # Stage 4: Store in database
    invoice = Invoice(
        invoice_number=extracted.get("invoice_number"),
        vendor_name=extracted.get("vendor_name"),
        vendor_address=extracted.get("vendor_address"),
        invoice_date=extracted.get("invoice_date"),
        due_date=extracted.get("due_date"),
        subtotal=extracted.get("subtotal"),
        tax_amount=extracted.get("tax_amount"),
        total_amount=extracted.get("total_amount"),
        currency=extracted.get("currency", "USD"),
        po_number=extracted.get("po_number"),
        file_path=str(path),
        file_hash=file_hash,
        raw_text=raw_text,
        extracted_json=json.dumps(extracted),
        status="pending",
    )

    for item_data in line_items_data:
        if isinstance(item_data, dict):
            invoice.line_items.append(
                LineItem(
                    description=item_data.get("description", ""),
                    quantity=item_data.get("quantity", 1.0),
                    unit_price=item_data.get("unit_price"),
                    amount=item_data.get("amount", 0.0),
                )
            )

    # Stage 5: Categorize
    invoice.category = categorize_invoice(invoice)

    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)

    # Stage 6: Duplicate detection
    dup_result = await check_duplicates(invoice, db)
    if dup_result.is_duplicate:
        invoice.duplicate_of_id = dup_result.matches[0].invoice_id
        invoice.validation_notes = (
            f"Potential duplicate of invoice #{dup_result.matches[0].invoice_id} "
            f"(score: {dup_result.matches[0].similarity_score}%)"
        )
        await db.commit()

    # Stage 7: PO validation
    validation = await validate_against_po(invoice, db)
    if not validation.valid:
        notes = "; ".join(validation.discrepancies)
        existing_notes = invoice.validation_notes or ""
        invoice.validation_notes = f"{existing_notes}; {notes}".strip("; ") if existing_notes else notes
        await db.commit()

    logger.info(
        "Pipeline complete: id=%s vendor=%s total=%s category=%s",
        invoice.id, invoice.vendor_name, invoice.total_amount, invoice.category,
    )

    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "vendor_name": invoice.vendor_name,
        "total_amount": invoice.total_amount,
        "status": invoice.status,
        "category": invoice.category,
        "is_duplicate": dup_result.is_duplicate,
        "validation_valid": validation.valid,
        "validation_discrepancies": validation.discrepancies,
    }


async def process_directory(directory: str, db: AsyncSession) -> list[dict]:
    """Batch process all invoice files in a directory.

    Scans the directory for supported file types and runs each through
    the full processing pipeline. This is the batch data ingestion path.

    Args:
        directory: Path to directory containing invoice files.
        db: Async database session.

    Returns:
        List of processing results for each file.
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    results: list[dict] = []
    files = sorted(
        f for f in dir_path.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    logger.info("Batch ingestion: found %d files in %s", len(files), directory)

    for file_path in files:
        try:
            result = await process_invoice(str(file_path), db)
            results.append(result)
        except Exception as e:
            logger.error("Batch ingestion: failed to process %s: %s", file_path.name, e)
            results.append({"file": str(file_path), "error": str(e)})

    logger.info("Batch ingestion complete: %d/%d succeeded",
                sum(1 for r in results if "error" not in r), len(results))
    return results


async def fetch_and_process(url: str, db: AsyncSession, filename: str | None = None) -> dict:
    """Fetch an invoice from a remote URL via HTTP and process it through the pipeline.

    Downloads the file from the given URL, saves it to the upload directory,
    and runs it through the full extraction pipeline. This is the HTTP-based
    data ingestion path for processing invoices from external systems.

    Args:
        url: Remote URL to fetch the invoice file from.
        db: Async database session.
        filename: Optional override for the saved filename.

    Returns:
        Processing result dict.
    """
    from urllib.parse import urlparse

    if not filename:
        parsed = urlparse(url)
        filename = Path(parsed.path).name or "downloaded_invoice"
        if not Path(filename).suffix:
            filename += ".pdf"

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type from URL: {suffix}")

    upload_dir = Path(settings.upload_dir)
    dest = upload_dir / filename
    counter = 1
    while dest.exists():
        dest = upload_dir / f"{Path(filename).stem}_{counter}{suffix}"
        counter += 1

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)

    logger.info("Fetched %d bytes from %s → %s", len(resp.content), url, dest.name)
    return await process_invoice(str(dest), db)


async def get_pipeline_status(db: AsyncSession) -> dict:
    """Get current pipeline processing status and statistics.

    Returns counts of invoices by status, recent processing results,
    and system configuration info.
    """
    from sqlalchemy import func

    total = (await db.execute(select(func.count(Invoice.id)))).scalar() or 0
    pending = (await db.execute(
        select(func.count(Invoice.id)).where(Invoice.status == "pending")
    )).scalar() or 0
    approved = (await db.execute(
        select(func.count(Invoice.id)).where(Invoice.status == "approved")
    )).scalar() or 0
    rejected = (await db.execute(
        select(func.count(Invoice.id)).where(Invoice.status == "rejected")
    )).scalar() or 0
    exported = (await db.execute(
        select(func.count(Invoice.id)).where(Invoice.status == "exported")
    )).scalar() or 0

    duplicates = (await db.execute(
        select(func.count(Invoice.id)).where(Invoice.duplicate_of_id.isnot(None))
    )).scalar() or 0

    return {
        "total_invoices": total,
        "by_status": {
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "exported": exported,
        },
        "duplicates_detected": duplicates,
        "ollama_model": settings.ollama_model,
        "ollama_url": settings.ollama_base_url,
        "watch_dir": settings.watch_dir,
        "supported_formats": sorted(SUPPORTED_EXTENSIONS),
    }
