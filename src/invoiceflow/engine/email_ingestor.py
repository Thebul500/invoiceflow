"""Email inbox data ingestion — fetches invoices from IMAP mailbox.

Connects to an IMAP server, searches for unread emails with invoice
attachments (PDF, image), downloads them, and feeds them through the
extraction pipeline. Also provides synchronous HTTP helpers for fetching
invoice files from URLs.

Data ingestion paths:
- IMAP mailbox polling: connects to email server, downloads invoice attachments
- HTTP fetching: httpx.get for synchronous URL downloads
"""

import email as email_stdlib
import imaplib
import logging
from email.policy import default as email_default_policy
from pathlib import Path

import httpx

from ..config import settings
from .ingestor import SUPPORTED_EXTENSIONS, ingest_file

logger = logging.getLogger(__name__)

# Email subjects that likely contain invoices
INVOICE_SUBJECT_KEYWORDS = [
    "invoice", "bill", "statement", "payment", "receipt",
    "amount due", "remittance", "purchase order",
]


def fetch_invoice_url(url: str, dest_dir: str | None = None) -> str | None:
    """Synchronous HTTP fetch for downloading invoice files from URLs.

    Uses httpx.get to download a file and save it locally. This is the
    synchronous data ingestion helper for CLI and scripting use.

    Args:
        url: URL to fetch the invoice file from.
        dest_dir: Directory to save the file. Defaults to upload_dir.

    Returns:
        Local file path of the downloaded file, or None on failure.
    """
    dest_path = Path(dest_dir or settings.upload_dir)
    dest_path.mkdir(parents=True, exist_ok=True)

    parsed_name = Path(url.split("/")[-1].split("?")[0]) if "/" in url else Path("download")
    filename = parsed_name.name or "downloaded_invoice"
    if not Path(filename).suffix:
        filename += ".pdf"

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        logger.warning("Unsupported file type from URL: %s", suffix)
        return None

    dest = dest_path / filename
    counter = 1
    while dest.exists():
        dest = dest_path / f"{Path(filename).stem}_{counter}{suffix}"
        counter += 1

    try:
        resp = httpx.get(url, follow_redirects=True, timeout=60.0)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        logger.info("HTTP fetch: downloaded %d bytes from %s → %s", len(resp.content), url, dest.name)
        return str(dest)
    except httpx.HTTPError as exc:
        logger.error("HTTP fetch failed for %s: %s", url, exc)
        return None


def connect_imap(
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    use_ssl: bool | None = None,
) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
    """Connect and authenticate to an IMAP server.

    Uses settings from config if parameters are not provided.

    Returns:
        Authenticated IMAP connection.

    Raises:
        imaplib.IMAP4.error: On connection or auth failure.
    """
    host = host or settings.imap_host
    port = port or settings.imap_port
    user = user or settings.imap_user
    password = password or settings.imap_password
    use_ssl = use_ssl if use_ssl is not None else settings.imap_use_ssl

    if not user or not password:
        raise ValueError("IMAP user and password must be configured")

    logger.info("Connecting to IMAP server %s:%d (SSL=%s)", host, port, use_ssl)

    conn: imaplib.IMAP4_SSL | imaplib.IMAP4
    if use_ssl:
        conn = imaplib.IMAP4_SSL(host, port)
    else:
        conn = imaplib.IMAP4(host, port)

    conn.login(user, password)
    logger.info("IMAP login successful for %s", user)
    return conn


def search_invoice_emails(
    conn: imaplib.IMAP4 | imaplib.IMAP4_SSL,
    folder: str | None = None,
    mark_read: bool = True,
) -> list[tuple[str, bytes]]:
    """Search IMAP folder for unread emails with invoice-related subjects.

    Downloads matching emails and extracts their attachments (PDF, images).

    Args:
        conn: Authenticated IMAP connection.
        folder: IMAP folder to search. Defaults to INBOX.
        mark_read: Whether to mark processed emails as read.

    Returns:
        List of (filename, file_data) tuples for invoice attachments found.
    """
    folder = folder or settings.imap_folder
    conn.select(folder)

    # Search for unread messages
    status, msg_ids = conn.search(None, "UNSEEN")
    if status != "OK" or not msg_ids[0]:
        logger.info("No unread emails found in %s", folder)
        return []

    ids = msg_ids[0].split()
    logger.info("Found %d unread emails in %s", len(ids), folder)

    attachments: list[tuple[str, bytes]] = []

    for msg_id in ids:
        status, msg_data = conn.fetch(msg_id, "(RFC822)")
        if status != "OK" or not msg_data[0]:
            continue

        raw_email = msg_data[0][1]
        if not isinstance(raw_email, bytes):
            continue

        msg = email_stdlib.message_from_bytes(raw_email, policy=email_default_policy)
        subject = str(msg.get("Subject", "")).lower()

        # Check if subject is invoice-related
        is_invoice = any(kw in subject for kw in INVOICE_SUBJECT_KEYWORDS)
        if not is_invoice:
            continue

        logger.info("Processing invoice email: %s", msg.get("Subject"))

        # Extract attachments from this email
        msg_attachments_found = 0
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" not in disposition:
                continue

            fname = part.get_filename()
            if not fname:
                continue

            suffix = Path(fname).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                continue

            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                attachments.append((fname, payload))
                msg_attachments_found += 1
                logger.info("Found invoice attachment: %s (%d bytes)", fname, len(payload))

        # If no file attachments but email body mentions invoice, save as .eml
        if msg_attachments_found == 0:
            eml_name = f"email_{msg_id.decode()}.eml"
            attachments.append((eml_name, raw_email))

        if mark_read:
            conn.store(msg_id, "+FLAGS", "\\Seen")

    return attachments


async def ingest_from_mailbox(
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    folder: str | None = None,
) -> list[dict]:
    """Full IMAP email data ingestion pipeline.

    Connects to an IMAP mailbox, searches for unread invoice emails,
    downloads attachments, and feeds each through the invoice extraction
    pipeline.

    Args:
        host: IMAP server hostname. Defaults to config.
        port: IMAP server port. Defaults to config.
        user: IMAP username. Defaults to config.
        password: IMAP password. Defaults to config.
        folder: IMAP folder to scan. Defaults to config.

    Returns:
        List of ingestion result dicts for each processed attachment.
    """
    results: list[dict] = []

    try:
        conn = connect_imap(host, port, user, password)
    except (imaplib.IMAP4.error, ValueError, OSError) as exc:
        logger.error("IMAP connection failed: %s", exc)
        return results

    try:
        attachments = search_invoice_emails(conn, folder)
        logger.info("Email ingestion: found %d invoice attachments", len(attachments))

        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)

        for fname, data in attachments:
            # Save attachment to temp file, then ingest
            dest = upload_dir / fname
            counter = 1
            while dest.exists():
                stem = Path(fname).stem
                suffix = Path(fname).suffix
                dest = upload_dir / f"{stem}_{counter}{suffix}"
                counter += 1

            dest.write_bytes(data)
            logger.info("Saved email attachment: %s", dest)

            result = await ingest_file(str(dest))
            if result:
                results.append(result)
            else:
                results.append({"file": str(dest), "error": "Ingestion failed"})

    except Exception as exc:
        logger.error("Email ingestion error: %s", exc)
    finally:
        try:
            conn.logout()
        except Exception:
            logger.debug("IMAP logout failed (connection may already be closed)")

    logger.info(
        "Email ingestion complete: %d/%d succeeded",
        sum(1 for r in results if "error" not in r),
        len(results),
    )
    return results


def fetch_and_save_invoice(url: str) -> str | None:
    """Fetch an invoice from a URL using HTTP and save locally.

    This is a convenience wrapper using httpx.get for web scraping
    and data ingestion of invoice files from vendor portals.

    Args:
        url: The URL to fetch.

    Returns:
        Path to the saved file, or None on failure.
    """
    return fetch_invoice_url(url)
