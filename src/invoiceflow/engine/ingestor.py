"""Watch folder ingestor — monitors a directory for new invoice files and processes them.

Uses watchdog to detect new PDF, image, and text files dropped into the watch folder,
then runs them through the full extraction pipeline (text extraction → LLM → DB storage).
This is the primary data ingestion path for batch/automated invoice processing.

Also supports HTTP URL-based data ingestion: fetches invoice files from remote URLs
and processes them through the same pipeline.
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from ..config import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp", ".txt", ".eml"}


class InvoiceFileHandler(FileSystemEventHandler):
    """Handles new files in the watch folder by queuing them for processing."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            logger.info("New file detected in watch folder: %s", path.name)
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._queue.put_nowait, str(path))

    @property
    def queue(self) -> "asyncio.Queue[str]":
        return self._queue


async def ingest_file(file_path: str) -> dict | None:
    """Ingest a single file: copy to uploads, extract data, store in DB.

    Returns the created invoice data dict, or None on failure.
    """
    from ..database import async_session
    from ..engine.categorizer import categorize_invoice
    from ..engine.duplicates import check_duplicates
    from ..engine.extractor import compute_file_hash, extract_invoice_data
    from ..models import Invoice, LineItem

    path = Path(file_path)
    if not path.exists():
        logger.warning("File not found for ingestion: %s", file_path)
        return None

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        logger.warning("Unsupported file type: %s", path.suffix)
        return None

    upload_dir = Path(settings.upload_dir)
    dest = upload_dir / path.name
    counter = 1
    while dest.exists():
        dest = upload_dir / f"{path.stem}_{counter}{path.suffix}"
        counter += 1

    shutil.copy2(str(path), str(dest))
    logger.info("Copied %s to uploads: %s", path.name, dest)

    try:
        extracted = await extract_invoice_data(str(dest))
    except Exception as e:
        logger.error("Extraction failed for %s: %s", dest.name, e)
        extracted = {
            "raw_text": "",
            "file_hash": compute_file_hash(str(dest)),
        }

    line_items_data = extracted.pop("line_items", [])
    raw_text = extracted.pop("raw_text", "")
    file_hash = extracted.pop("file_hash", "")

    async with async_session() as db:
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
            file_path=str(dest),
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

        invoice.category = categorize_invoice(invoice)
        db.add(invoice)
        await db.commit()
        await db.refresh(invoice)

        dup_result = await check_duplicates(invoice, db)
        if dup_result.is_duplicate:
            invoice.duplicate_of_id = dup_result.matches[0].invoice_id  # type: ignore[assignment]
            invoice.validation_notes = (  # type: ignore[assignment]
                f"Potential duplicate of invoice #{dup_result.matches[0].invoice_id} "
                f"(score: {dup_result.matches[0].similarity_score}%)"
            )
            await db.commit()

        logger.info(
            "Ingested invoice: id=%s vendor=%s total=%s",
            invoice.id,
            invoice.vendor_name,
            invoice.total_amount,
        )
        return {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "vendor_name": invoice.vendor_name,
            "total_amount": invoice.total_amount,
            "status": invoice.status,
            "category": invoice.category,
        }


async def process_queue(handler: InvoiceFileHandler) -> None:
    """Continuously process files from the watch folder queue."""
    while True:
        file_path = await handler.queue.get()
        try:
            result = await ingest_file(file_path)
            if result:
                logger.info("Successfully ingested: %s", result.get("invoice_number"))
        except Exception as e:
            logger.error("Failed to ingest %s: %s", file_path, e)
        finally:
            handler.queue.task_done()


def start_watcher(watch_dir: str | None = None) -> tuple[BaseObserver, InvoiceFileHandler]:
    """Start the watch folder observer.

    Returns the observer and handler so callers can manage the lifecycle.
    """
    watch_path = Path(watch_dir or settings.watch_dir)
    watch_path.mkdir(parents=True, exist_ok=True)

    handler = InvoiceFileHandler()
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=False)
    observer.daemon = True
    observer.start()

    logger.info("Watch folder ingestor started: %s", watch_path)
    return observer, handler


async def fetch_from_url(url: str, filename: str | None = None) -> dict | None:
    """Fetch an invoice file from a remote URL and ingest it.

    This is the HTTP-based data ingestion path. Downloads the file from the URL,
    saves it to the upload directory, and runs it through the extraction pipeline.

    Args:
        url: Remote URL to fetch the invoice file from.
        filename: Optional override for the saved filename. Auto-detected from URL if omitted.

    Returns:
        Ingested invoice data dict, or None on failure.
    """
    if not filename:
        parsed = urlparse(url)
        filename = Path(parsed.path).name or "downloaded_invoice"
        if not Path(filename).suffix:
            filename += ".pdf"

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        logger.warning("Unsupported file type from URL: %s", suffix)
        return None

    upload_dir = Path(settings.upload_dir)
    dest = upload_dir / filename
    counter = 1
    while dest.exists():
        dest = upload_dir / f"{Path(filename).stem}_{counter}{suffix}"
        counter += 1

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        logger.info("Fetched %d bytes from %s → %s", len(resp.content), url, dest.name)
    except httpx.HTTPError as e:
        logger.error("Failed to fetch URL %s: %s", url, e)
        return None

    return await ingest_file(str(dest))


async def run_ingestor(watch_dir: str | None = None) -> None:
    """Run the watch folder ingestor as an async task.

    Starts the filesystem observer and processes detected files.
    """
    observer, handler = start_watcher(watch_dir)
    loop = asyncio.get_running_loop()
    handler.set_loop(loop)

    try:
        await process_queue(handler)
    finally:
        observer.stop()
        observer.join()
