"""Invoice API routes — upload, process, validate, approve, export."""

import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_db
from ..engine.categorizer import categorize_invoice
from ..engine.duplicates import check_duplicates
from ..engine.exporter import export_csv, export_iif
from ..engine.extractor import compute_file_hash, extract_invoice_data
from ..engine.ingestor import SUPPORTED_EXTENSIONS, fetch_from_url, ingest_file
from ..engine.pipeline import (
    fetch_and_process,
    get_pipeline_status,
    process_directory,
    process_invoice,
)
from ..engine.validator import validate_against_po
from ..models import Invoice, LineItem
from ..schemas import (
    BatchProcessRequest,
    BatchProcessResponse,
    DuplicateCheckResult,
    ExportRequest,
    ExportResponse,
    FetchUrlRequest,
    IngestRequest,
    IngestResponse,
    InvoiceCreate,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceStatusUpdate,
    PipelineResult,
    PipelineStatusResponse,
    ValidationResult,
    WatchFolderStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/invoices", tags=["invoices"])


async def _fresh_invoice(db: AsyncSession, invoice_id: int) -> Invoice:
    """Re-fetch an invoice with all attributes and relationships loaded."""
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(Invoice.id == invoice_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one()


@router.post("/upload", response_model=InvoiceResponse, status_code=201)
async def upload_invoice(file: UploadFile, db: AsyncSession = Depends(get_db)):
    """Upload an invoice file (PDF, image, text) for AI extraction.

    The file is saved, text extracted, sent to Ollama for structured extraction,
    then stored in the database with automatic categorization and duplicate check.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    upload_dir = Path(settings.upload_dir)
    dest = upload_dir / file.filename
    counter = 1
    while dest.exists():
        stem = Path(file.filename).stem
        suffix = Path(file.filename).suffix
        dest = upload_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        extracted = await extract_invoice_data(str(dest))
    except Exception as e:
        logger.error("Extraction failed for %s: %s", dest, e)
        extracted = {
            "raw_text": "",
            "file_hash": compute_file_hash(str(dest)),
        }

    line_items_data = extracted.pop("line_items", [])
    raw_text = extracted.pop("raw_text", "")
    file_hash = extracted.pop("file_hash", "")

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
    invoice = await _fresh_invoice(db, invoice.id)

    dup_result = await check_duplicates(invoice, db)
    if dup_result.is_duplicate:
        invoice.duplicate_of_id = dup_result.matches[0].invoice_id
        invoice.validation_notes = (
            f"Potential duplicate of invoice #{dup_result.matches[0].invoice_id} "
            f"(score: {dup_result.matches[0].similarity_score}%)"
        )
        await db.commit()
        invoice = await _fresh_invoice(db, invoice.id)

    return invoice


@router.post("", response_model=InvoiceResponse, status_code=201)
async def create_invoice(data: InvoiceCreate, db: AsyncSession = Depends(get_db)):
    """Create an invoice manually (without file upload)."""
    invoice = Invoice(
        invoice_number=data.invoice_number,
        vendor_name=data.vendor_name,
        vendor_address=data.vendor_address,
        invoice_date=data.invoice_date,
        due_date=data.due_date,
        subtotal=data.subtotal,
        tax_amount=data.tax_amount,
        total_amount=data.total_amount,
        currency=data.currency,
        po_number=data.po_number,
        category=data.category,
        status="pending",
    )
    for item in data.line_items:
        invoice.line_items.append(
            LineItem(
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
            )
        )
    invoice.category = categorize_invoice(invoice)

    db.add(invoice)
    await db.commit()
    invoice = await _fresh_invoice(db, invoice.id)

    dup_result = await check_duplicates(invoice, db)
    if dup_result.is_duplicate:
        invoice.duplicate_of_id = dup_result.matches[0].invoice_id
        await db.commit()
        invoice = await _fresh_invoice(db, invoice.id)

    return invoice


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    status: str | None = None,
    vendor: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List invoices with optional filtering."""
    stmt = select(Invoice).options(selectinload(Invoice.line_items))
    count_stmt = select(func.count(Invoice.id))

    if status:
        stmt = stmt.where(Invoice.status == status)
        count_stmt = count_stmt.where(Invoice.status == status)
    if vendor:
        stmt = stmt.where(Invoice.vendor_name.ilike(f"%{vendor}%"))
        count_stmt = count_stmt.where(Invoice.vendor_name.ilike(f"%{vendor}%"))

    stmt = stmt.offset(skip).limit(limit).order_by(Invoice.id.desc())

    result = await db.execute(stmt)
    invoices = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return InvoiceListResponse(invoices=invoices, total=total)  # type: ignore[arg-type]


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single invoice by ID."""
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(Invoice.id == invoice_id)
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.patch("/{invoice_id}/status", response_model=InvoiceResponse)
async def update_invoice_status(
    invoice_id: int, update: InvoiceStatusUpdate, db: AsyncSession = Depends(get_db)
):
    """Update invoice status (approve, reject, etc.)."""
    stmt = select(Invoice).where(Invoice.id == invoice_id)
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = update.status
    await db.commit()

    invoice = await _fresh_invoice(db, invoice_id)

    if settings.webhook_url and update.status in ("approved", "rejected"):
        await _fire_webhook(invoice, update.status)

    return invoice


@router.post("/{invoice_id}/validate", response_model=ValidationResult)
async def validate_invoice(invoice_id: int, db: AsyncSession = Depends(get_db)):
    """Validate an invoice against its purchase order."""
    stmt = select(Invoice).where(Invoice.id == invoice_id)
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    validation = await validate_against_po(invoice, db)

    notes = "; ".join(validation.discrepancies) if validation.discrepancies else "Valid"
    invoice.validation_notes = notes
    await db.commit()

    return validation


@router.post("/{invoice_id}/duplicates", response_model=DuplicateCheckResult)
async def check_invoice_duplicates(invoice_id: int, db: AsyncSession = Depends(get_db)):
    """Check an invoice for potential duplicates."""
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(Invoice.id == invoice_id)
    )
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return await check_duplicates(invoice, db)


@router.post("/export", response_model=ExportResponse)
async def export_invoices(req: ExportRequest, db: AsyncSession = Depends(get_db)):
    """Export invoices to CSV or QuickBooks IIF format."""
    ids = req.invoice_ids if req.invoice_ids else None
    if req.format == "iif":
        path = await export_iif(db, ids)
    else:
        path = await export_csv(db, ids)

    count_stmt = select(func.count(Invoice.id))
    if ids:
        count_stmt = count_stmt.where(Invoice.id.in_(ids))
    else:
        count_stmt = count_stmt.where(Invoice.status == "approved")
    count_result = await db.execute(count_stmt)
    count = count_result.scalar() or 0

    return ExportResponse(file_path=path, format=req.format, invoice_count=count)


@router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest_local_file(req: IngestRequest):
    """Ingest a local invoice file by path.

    Copies the file to uploads, runs LLM extraction, and stores the invoice.
    This is the programmatic data ingestion endpoint for batch processing.
    """
    result = await ingest_file(req.file_path)
    if result is None:
        raise HTTPException(status_code=400, detail="Failed to ingest file — check path and format")
    return IngestResponse(**result)


@router.post("/fetch-url", response_model=IngestResponse, status_code=201)
async def fetch_invoice_from_url(req: FetchUrlRequest):
    """Fetch an invoice from a remote URL and ingest it.

    Downloads the file via HTTP, saves it locally, then runs the full
    extraction pipeline (text extraction → LLM → DB storage).
    This is the HTTP-based data ingestion endpoint.
    """
    result = await fetch_from_url(req.url, req.filename)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Failed to fetch or ingest from URL — check URL and file format",
        )
    return IngestResponse(**result)


@router.get("/watch-folder/status", response_model=WatchFolderStatus)
async def watch_folder_status():
    """Get the watch folder ingestion status."""
    return WatchFolderStatus(
        watch_dir=settings.watch_dir,
        supported_extensions=sorted(SUPPORTED_EXTENSIONS),
        active=True,
    )


@router.post("/pipeline/process", response_model=PipelineResult, status_code=201)
async def pipeline_process_file(req: IngestRequest, db: AsyncSession = Depends(get_db)):
    """Process a single invoice file through the full pipeline.

    Runs the complete workflow: ingest → extract (LLM) → validate → dedup → categorize.
    Returns detailed processing results including validation status.
    """
    try:
        result = await process_invoice(req.file_path, db)
        return PipelineResult(**result)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pipeline/batch", response_model=BatchProcessResponse)
async def pipeline_batch_process(req: BatchProcessRequest, db: AsyncSession = Depends(get_db)):
    """Batch process all invoice files in a directory.

    Scans the directory for supported file types (PDF, image, email, text)
    and runs each through the full extraction and validation pipeline.
    This is the batch data ingestion endpoint.
    """
    try:
        results = await process_directory(req.directory, db)
    except NotADirectoryError:
        raise HTTPException(status_code=400, detail="Not a valid directory")

    pipeline_results = []
    for r in results:
        if "error" in r:
            pipeline_results.append(PipelineResult(error=r["error"], file=r.get("file")))
        else:
            pipeline_results.append(PipelineResult(**r))

    successful = sum(1 for r in results if "error" not in r)
    return BatchProcessResponse(
        results=pipeline_results,
        total_processed=len(results),
        successful=successful,
        failed=len(results) - successful,
    )


@router.get("/pipeline/status", response_model=PipelineStatusResponse)
async def pipeline_status(db: AsyncSession = Depends(get_db)):
    """Get pipeline processing status and statistics."""
    status = await get_pipeline_status(db)
    return PipelineStatusResponse(**status)


async def _fire_webhook(invoice: Invoice, event: str):
    """Send a webhook notification for invoice status changes."""
    import httpx

    payload = {
        "event": f"invoice.{event}",
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "vendor_name": invoice.vendor_name,
        "total_amount": invoice.total_amount,
        "status": invoice.status,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(settings.webhook_url, json=payload)
    except Exception as e:
        logger.warning("Webhook failed: %s", e)
