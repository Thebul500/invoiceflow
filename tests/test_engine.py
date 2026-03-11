"""Direct async tests for engine modules — validator, exporter, duplicates, ingestor.

These tests call engine functions directly with real async DB sessions to ensure
coverage of the core domain logic paths.
"""

import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from invoiceflow.engine.categorizer import categorize_invoice
from invoiceflow.engine.duplicates import check_duplicates
from invoiceflow.engine.exporter import export_csv, export_iif
from invoiceflow.engine.extractor import parse_email
from invoiceflow.engine.ingestor import (
    fetch_from_url,
    ingest_file,
    start_watcher,
)
from invoiceflow.engine.validator import validate_against_po
from invoiceflow.models import Invoice, LineItem, PurchaseOrder


# --- Validator tests ---


@pytest.mark.asyncio
async def test_validate_matching_po(db_session):
    """Validator returns valid=True when invoice matches PO."""
    po = PurchaseOrder(
        po_number="PO-TEST-01",
        vendor_name="Acme Corp",
        total_amount=1000.00,
        status="open",
    )
    db_session.add(po)
    await db_session.commit()

    inv = Invoice(
        invoice_number="INV-V-01",
        vendor_name="Acme Corp",
        total_amount=1000.00,
        po_number="PO-TEST-01",
    )
    db_session.add(inv)
    await db_session.commit()

    result = await validate_against_po(inv, db_session)
    assert result.valid is True
    assert len(result.discrepancies) == 0
    assert result.po_number == "PO-TEST-01"
    assert result.po_amount == 1000.00


@pytest.mark.asyncio
async def test_validate_po_not_found(db_session):
    """Validator flags missing PO."""
    inv = Invoice(
        invoice_number="INV-V-02",
        vendor_name="Acme",
        total_amount=500.00,
        po_number="PO-MISSING",
    )
    db_session.add(inv)
    await db_session.commit()

    result = await validate_against_po(inv, db_session)
    assert result.valid is False
    assert any("not found" in d for d in result.discrepancies)


@pytest.mark.asyncio
async def test_validate_vendor_mismatch(db_session):
    """Validator flags vendor name mismatch."""
    po = PurchaseOrder(
        po_number="PO-VM-01",
        vendor_name="Acme Corp",
        total_amount=500.00,
        status="open",
    )
    db_session.add(po)
    await db_session.commit()

    inv = Invoice(
        vendor_name="Globex Inc",
        total_amount=500.00,
        po_number="PO-VM-01",
    )
    db_session.add(inv)
    await db_session.commit()

    result = await validate_against_po(inv, db_session)
    assert result.valid is False
    assert any("Vendor mismatch" in d for d in result.discrepancies)


@pytest.mark.asyncio
async def test_validate_amount_mismatch(db_session):
    """Validator flags amount discrepancy beyond tolerance."""
    po = PurchaseOrder(
        po_number="PO-AM-01",
        vendor_name="Acme",
        total_amount=1000.00,
        status="open",
    )
    db_session.add(po)
    await db_session.commit()

    inv = Invoice(
        vendor_name="Acme",
        total_amount=1200.00,
        po_number="PO-AM-01",
    )
    db_session.add(inv)
    await db_session.commit()

    result = await validate_against_po(inv, db_session)
    assert result.valid is False
    assert any("Amount mismatch" in d for d in result.discrepancies)


@pytest.mark.asyncio
async def test_validate_closed_po(db_session):
    """Validator flags closed PO status."""
    po = PurchaseOrder(
        po_number="PO-CL-01",
        vendor_name="Acme",
        total_amount=500.00,
        status="closed",
    )
    db_session.add(po)
    await db_session.commit()

    inv = Invoice(
        vendor_name="Acme",
        total_amount=500.00,
        po_number="PO-CL-01",
    )
    db_session.add(inv)
    await db_session.commit()

    result = await validate_against_po(inv, db_session)
    assert result.valid is False
    assert any("closed" in d for d in result.discrepancies)


@pytest.mark.asyncio
async def test_validate_no_po_number(db_session):
    """Invoice without PO number skips PO validation."""
    inv = Invoice(vendor_name="Acme", total_amount=100.00)
    db_session.add(inv)
    await db_session.commit()

    result = await validate_against_po(inv, db_session)
    assert result.valid is True
    assert any("skipped" in d.lower() for d in result.discrepancies)


# --- Exporter tests ---


@pytest.mark.asyncio
async def test_export_csv_with_line_items(db_session):
    """CSV export includes invoice and line item data."""
    inv = Invoice(
        invoice_number="INV-EX-01",
        vendor_name="Acme Corp",
        invoice_date="2026-03-01",
        due_date="2026-03-31",
        subtotal=200.00,
        tax_amount=16.00,
        total_amount=216.00,
        currency="USD",
        po_number="PO-100",
        category="Office Supplies",
        status="approved",
    )
    inv.line_items.append(
        LineItem(description="Paper", quantity=10, unit_price=10.0, amount=100.0)
    )
    inv.line_items.append(
        LineItem(description="Pens", quantity=20, unit_price=5.0, amount=100.0)
    )
    db_session.add(inv)
    await db_session.commit()

    path = await export_csv(db_session)
    content = Path(path).read_text()
    assert "INV-EX-01" in content
    assert "Acme Corp" in content
    assert "Paper" in content
    assert "Pens" in content


@pytest.mark.asyncio
async def test_export_csv_no_line_items(db_session):
    """CSV export handles invoices without line items."""
    inv = Invoice(
        invoice_number="INV-EX-02",
        vendor_name="Solo Corp",
        total_amount=50.00,
        status="approved",
    )
    db_session.add(inv)
    await db_session.commit()

    path = await export_csv(db_session)
    content = Path(path).read_text()
    assert "INV-EX-02" in content
    assert "Solo Corp" in content


@pytest.mark.asyncio
async def test_export_csv_specific_ids(db_session):
    """CSV export with specific invoice IDs."""
    inv1 = Invoice(invoice_number="A", vendor_name="V1", total_amount=10.0, status="pending")
    inv2 = Invoice(invoice_number="B", vendor_name="V2", total_amount=20.0, status="pending")
    db_session.add_all([inv1, inv2])
    await db_session.commit()
    await db_session.refresh(inv1)

    path = await export_csv(db_session, [inv1.id])
    content = Path(path).read_text()
    assert "V1" in content
    assert "V2" not in content


@pytest.mark.asyncio
async def test_export_iif_with_line_items(db_session):
    """IIF export produces valid QuickBooks format."""
    inv = Invoice(
        invoice_number="INV-IIF-01",
        vendor_name="Tech Vendor",
        invoice_date="2026-03-01",
        total_amount=500.00,
        category="IT & Software",
        status="approved",
    )
    inv.line_items.append(
        LineItem(description="Software license", quantity=1, unit_price=500.0, amount=500.0)
    )
    db_session.add(inv)
    await db_session.commit()

    path = await export_iif(db_session)
    content = Path(path).read_text()
    assert "!TRNS" in content
    assert "!SPL" in content
    assert "ENDTRNS" in content
    assert "BILL" in content
    assert "Tech Vendor" in content
    assert "Software license" in content


@pytest.mark.asyncio
async def test_export_iif_no_line_items(db_session):
    """IIF export handles invoices without line items."""
    inv = Invoice(
        invoice_number="INV-IIF-02",
        vendor_name="Simple Vendor",
        invoice_date="2026-02-15",
        total_amount=300.00,
        category="General Expense",
        status="approved",
    )
    db_session.add(inv)
    await db_session.commit()

    path = await export_iif(db_session)
    content = Path(path).read_text()
    assert "Simple Vendor" in content
    assert "ENDTRNS" in content


# --- Duplicate detection (DB path) ---


@pytest.mark.asyncio
async def test_check_duplicates_exact_hash(db_session):
    """Duplicate detection catches exact file hash matches."""
    inv1 = Invoice(
        id=1,
        invoice_number="INV-D-01",
        vendor_name="Acme",
        total_amount=100.0,
        file_hash="abc123",
    )
    inv2 = Invoice(
        id=2,
        invoice_number="INV-D-02",
        vendor_name="Globex",
        total_amount=200.0,
        file_hash="abc123",
    )
    db_session.add_all([inv1, inv2])
    await db_session.commit()

    result = await check_duplicates(inv2, db_session)
    assert result.is_duplicate is True
    assert result.matches[0].similarity_score == 100.0


@pytest.mark.asyncio
async def test_check_duplicates_fuzzy_match(db_session):
    """Duplicate detection catches fuzzy matches above threshold."""
    inv1 = Invoice(
        id=1,
        invoice_number="INV-001",
        vendor_name="Acme Corp",
        total_amount=500.0,
    )
    inv2 = Invoice(
        id=2,
        invoice_number="INV-001",
        vendor_name="Acme Corp",
        total_amount=500.0,
    )
    db_session.add_all([inv1, inv2])
    await db_session.commit()

    result = await check_duplicates(inv2, db_session, threshold=80.0)
    assert result.is_duplicate is True
    assert len(result.matches) >= 1


@pytest.mark.asyncio
async def test_check_duplicates_no_match(db_session):
    """No duplicates found for unique invoice."""
    inv1 = Invoice(
        id=1,
        invoice_number="INV-X-01",
        vendor_name="Alpha Corp",
        total_amount=100.0,
    )
    inv2 = Invoice(
        id=2,
        invoice_number="INV-Y-99",
        vendor_name="Beta LLC",
        total_amount=50000.0,
    )
    db_session.add_all([inv1, inv2])
    await db_session.commit()

    result = await check_duplicates(inv2, db_session)
    assert result.is_duplicate is False


# --- Email parsing ---


def test_parse_email_plain_text():
    """Parse .eml file extracts headers and body."""
    msg = MIMEMultipart()
    msg["From"] = "vendor@acme.com"
    msg["To"] = "ap@company.com"
    msg["Subject"] = "Invoice INV-001"
    msg["Date"] = "Mon, 01 Mar 2026 10:00:00 -0600"
    msg.attach(MIMEText("Please find attached invoice INV-001 for $500.00", "plain"))

    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False, mode="wb") as f:
        f.write(msg.as_bytes())
        eml_path = f.name

    body, attachments = parse_email(eml_path)
    assert "vendor@acme.com" in body
    assert "Invoice INV-001" in body
    assert "$500.00" in body
    assert len(attachments) == 0


def test_parse_email_with_attachment():
    """Parse .eml file extracts attachments."""
    from email.mime.application import MIMEApplication

    msg = MIMEMultipart()
    msg["From"] = "billing@vendor.com"
    msg["Subject"] = "Invoice attached"
    msg.attach(MIMEText("See attachment.", "plain"))

    pdf_data = b"%PDF-1.4 fake pdf content"
    attachment = MIMEApplication(pdf_data, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename="invoice.pdf")
    msg.attach(attachment)

    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False, mode="wb") as f:
        f.write(msg.as_bytes())
        eml_path = f.name

    body, attachments = parse_email(eml_path)
    assert "billing@vendor.com" in body
    assert len(attachments) == 1
    assert attachments[0][0] == "invoice.pdf"
    assert b"PDF" in attachments[0][1]


# --- Ingestor: ingest_file full path ---


@pytest.mark.asyncio
async def test_ingest_file_full_pipeline(db_session):
    """Full file ingestion pipeline with mocked Ollama."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="inv_"
    ) as f:
        f.write("Invoice #INGEST-001\nVendor: Test Corp\nTotal: $250.00")
        f.flush()
        txt_path = f.name

    with patch(
        "invoiceflow.engine.extractor.extract_with_ollama",
        new_callable=AsyncMock,
        return_value={
            "invoice_number": "INGEST-001",
            "vendor_name": "Test Corp",
            "total_amount": 250.00,
            "line_items": [
                {"description": "Service fee", "quantity": 1, "unit_price": 250.0, "amount": 250.0}
            ],
        },
    ):
        result = await ingest_file(txt_path)

    assert result is not None
    assert result["invoice_number"] == "INGEST-001"
    assert result["vendor_name"] == "Test Corp"
    assert result["total_amount"] == 250.00
    assert result["status"] == "pending"


# --- Ingestor: fetch_from_url ---


@pytest.mark.asyncio
async def test_fetch_from_url_success():
    """URL fetching downloads file and ingests it."""
    mock_response = AsyncMock()
    mock_response.content = b"Invoice text content here"
    mock_response.raise_for_status = lambda: None

    mock_ingest_result = {
        "id": 1,
        "invoice_number": "URL-001",
        "vendor_name": "Remote Vendor",
        "total_amount": 750.00,
        "status": "pending",
        "category": "General Expense",
    }

    with (
        patch("invoiceflow.engine.ingestor.httpx.AsyncClient") as mock_client_cls,
        patch(
            "invoiceflow.engine.ingestor.ingest_file",
            new_callable=AsyncMock,
            return_value=mock_ingest_result,
        ),
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_from_url("https://example.com/invoices/invoice.pdf")

    assert result is not None
    assert result["invoice_number"] == "URL-001"


@pytest.mark.asyncio
async def test_fetch_from_url_unsupported_type():
    """URL fetch rejects unsupported file types."""
    result = await fetch_from_url(
        "https://example.com/file.docx", filename="doc.docx"
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_from_url_http_error():
    """URL fetch handles HTTP errors gracefully."""
    import httpx as httpx_mod

    with patch("invoiceflow.engine.ingestor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx_mod.HTTPError("Connection failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_from_url("https://example.com/invoice.pdf")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_from_url_auto_filename():
    """URL fetch auto-detects filename from URL path."""
    mock_response = AsyncMock()
    mock_response.content = b"content"
    mock_response.raise_for_status = lambda: None

    mock_ingest = AsyncMock(return_value={"id": 1, "status": "pending"})

    with (
        patch("invoiceflow.engine.ingestor.httpx.AsyncClient") as mock_client_cls,
        patch("invoiceflow.engine.ingestor.ingest_file", mock_ingest),
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        # URL with no extension should default to .pdf
        result = await fetch_from_url("https://example.com/download")

    assert result is not None


# --- Watch folder ---


def test_start_watcher():
    """start_watcher creates observer and handler."""
    with tempfile.TemporaryDirectory() as tmpdir:
        observer, handler = start_watcher(tmpdir)
        assert observer.is_alive()
        assert handler.queue.empty()
        observer.stop()
        observer.join(timeout=2)


# --- Categorizer additional categories ---


def test_categorize_utilities():
    """Utility keywords matched."""
    inv = Invoice(vendor_name="ComEd Electric", line_items=[])
    inv.line_items.append(LineItem(description="Monthly electricity", amount=200.0))
    assert categorize_invoice(inv) == "Utilities"


def test_categorize_facilities():
    """Facilities keywords matched."""
    inv = Invoice(vendor_name="BuildRight", line_items=[])
    inv.line_items.append(LineItem(description="HVAC maintenance repair", amount=1500.0))
    assert categorize_invoice(inv) == "Facilities & Maintenance"


def test_categorize_marketing():
    """Marketing keywords matched."""
    inv = Invoice(vendor_name="AdAgency", line_items=[])
    inv.line_items.append(LineItem(description="Google advertising campaign", amount=3000.0))
    assert categorize_invoice(inv) == "Marketing & Advertising"


def test_categorize_raw_materials():
    """Raw materials keywords matched."""
    inv = Invoice(vendor_name="Steel Supply Co", line_items=[])
    inv.line_items.append(LineItem(description="Steel raw material supply", amount=10000.0))
    assert categorize_invoice(inv) == "Raw Materials"


def test_categorize_insurance():
    """Insurance keywords matched."""
    inv = Invoice(vendor_name="SafeGuard Insurance", line_items=[])
    inv.line_items.append(LineItem(description="Annual liability insurance premium", amount=5000.0))
    assert categorize_invoice(inv) == "Insurance"
