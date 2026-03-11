"""Tests for the pipeline orchestrator — processing invoices through the full workflow.

Tests the pipeline module against real local files (text, PDF, email),
real database operations, and real categorization/validation/dedup logic.
Only the Ollama LLM call is mocked since it requires a running LLM server.
"""

import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from invoiceflow.engine.pipeline import (
    fetch_and_process,
    get_pipeline_status,
    process_directory,
    process_invoice,
)
from invoiceflow.models import Invoice, PurchaseOrder


MOCK_EXTRACTION = {
    "invoice_number": "INV-PIPE-001",
    "vendor_name": "Pipeline Test Corp",
    "vendor_address": "456 Test Ave",
    "invoice_date": "2026-03-10",
    "due_date": "2026-04-10",
    "subtotal": 400.00,
    "tax_amount": 32.00,
    "total_amount": 432.00,
    "currency": "USD",
    "po_number": None,
    "line_items": [
        {"description": "Consulting services", "quantity": 8, "unit_price": 50.0, "amount": 400.0},
    ],
}


def _mock_ollama():
    """Patch Ollama extraction to return structured data."""
    return patch(
        "invoiceflow.engine.extractor.extract_with_ollama",
        new_callable=AsyncMock,
        return_value=MOCK_EXTRACTION.copy(),
    )


# --- process_invoice tests ---


@pytest.mark.asyncio
async def test_process_invoice_text_file(db_session):
    """Pipeline processes a real .txt invoice file end-to-end."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="inv_pipe_"
    ) as f:
        f.write(
            "INVOICE\n"
            "Invoice #: INV-PIPE-001\n"
            "From: Pipeline Test Corp\n"
            "Date: 2026-03-10\n"
            "Due: 2026-04-10\n\n"
            "Consulting services    8 hrs x $50.00    $400.00\n"
            "Tax: $32.00\n"
            "Total: $432.00\n"
        )
        f.flush()
        txt_path = f.name

    with _mock_ollama():
        result = await process_invoice(txt_path, db_session)

    assert result["id"] is not None
    assert result["invoice_number"] == "INV-PIPE-001"
    assert result["vendor_name"] == "Pipeline Test Corp"
    assert result["total_amount"] == 432.00
    assert result["status"] == "pending"
    assert result["category"] == "Professional Services"
    assert result["is_duplicate"] is False
    assert result["validation_valid"] is True  # no PO → skipped


@pytest.mark.asyncio
async def test_process_invoice_with_po_validation(db_session):
    """Pipeline validates invoice against a matching PO."""
    po = PurchaseOrder(
        po_number="PO-PIPE-01",
        vendor_name="Pipeline Test Corp",
        total_amount=432.00,
        status="open",
    )
    db_session.add(po)
    await db_session.commit()

    mock_data = {**MOCK_EXTRACTION, "po_number": "PO-PIPE-01"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Invoice with PO\nPO: PO-PIPE-01\nTotal: $432.00")
        f.flush()
        txt_path = f.name

    with patch(
        "invoiceflow.engine.extractor.extract_with_ollama",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        result = await process_invoice(txt_path, db_session)

    assert result["validation_valid"] is True
    assert result["validation_discrepancies"] == []


@pytest.mark.asyncio
async def test_process_invoice_po_amount_mismatch(db_session):
    """Pipeline flags PO amount mismatch."""
    po = PurchaseOrder(
        po_number="PO-PIPE-02",
        vendor_name="Pipeline Test Corp",
        total_amount=200.00,  # mismatch
        status="open",
    )
    db_session.add(po)
    await db_session.commit()

    mock_data = {**MOCK_EXTRACTION, "po_number": "PO-PIPE-02"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Invoice with PO mismatch")
        f.flush()
        txt_path = f.name

    with patch(
        "invoiceflow.engine.extractor.extract_with_ollama",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        result = await process_invoice(txt_path, db_session)

    assert result["validation_valid"] is False
    assert any("Amount mismatch" in d for d in result["validation_discrepancies"])


@pytest.mark.asyncio
async def test_process_invoice_duplicate_detection(db_session):
    """Pipeline detects duplicate when same invoice processed twice."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Duplicate test invoice")
        f.flush()
        txt_path = f.name

    with _mock_ollama():
        result1 = await process_invoice(txt_path, db_session)

    assert result1["is_duplicate"] is False

    # Process the same content again (different file, same extracted data)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Duplicate test invoice copy")
        f.flush()
        txt_path2 = f.name

    with _mock_ollama():
        result2 = await process_invoice(txt_path2, db_session)

    assert result2["is_duplicate"] is True


@pytest.mark.asyncio
async def test_process_invoice_file_not_found(db_session):
    """Pipeline raises FileNotFoundError for missing files."""
    with pytest.raises(FileNotFoundError):
        await process_invoice("/nonexistent/invoice.pdf", db_session)


@pytest.mark.asyncio
async def test_process_invoice_unsupported_type(db_session):
    """Pipeline raises ValueError for unsupported file types."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(b"fake docx")
        f.flush()

    with pytest.raises(ValueError, match="Unsupported"):
        await process_invoice(f.name, db_session)


@pytest.mark.asyncio
async def test_process_invoice_email_file(db_session):
    """Pipeline processes a real .eml file."""
    msg = MIMEMultipart()
    msg["From"] = "billing@vendor.com"
    msg["To"] = "ap@company.com"
    msg["Subject"] = "Invoice INV-EMAIL-001"
    msg["Date"] = "Mon, 10 Mar 2026 10:00:00 -0600"
    msg.attach(MIMEText("Invoice INV-EMAIL-001\nAmount: $500.00", "plain"))

    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False, mode="wb") as f:
        f.write(msg.as_bytes())
        eml_path = f.name

    with _mock_ollama():
        result = await process_invoice(eml_path, db_session)

    assert result["id"] is not None
    assert result["status"] == "pending"


# --- process_directory tests ---


@pytest.mark.asyncio
async def test_process_directory_batch(db_session):
    """Batch process multiple invoice files from a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create multiple invoice files
        for i in range(3):
            path = Path(tmpdir) / f"invoice_{i}.txt"
            path.write_text(f"Invoice #{i}\nVendor: Vendor {i}\nTotal: ${100 * (i + 1):.2f}")

        # Also create an unsupported file that should be skipped
        (Path(tmpdir) / "readme.docx").write_bytes(b"not an invoice")

        with _mock_ollama():
            results = await process_directory(tmpdir, db_session)

    assert len(results) == 3  # only .txt files processed, .docx skipped
    assert all("error" not in r for r in results)


@pytest.mark.asyncio
async def test_process_directory_empty(db_session):
    """Batch process on empty directory returns empty results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results = await process_directory(tmpdir, db_session)

    assert results == []


@pytest.mark.asyncio
async def test_process_directory_not_a_dir(db_session):
    """Batch process raises for non-directory path."""
    with pytest.raises(NotADirectoryError):
        await process_directory("/nonexistent/dir", db_session)


# --- fetch_and_process tests ---


@pytest.mark.asyncio
async def test_fetch_and_process_success(db_session):
    """HTTP fetch and process downloads file and runs pipeline."""
    mock_response = AsyncMock()
    mock_response.content = b"Invoice #FETCH-001\nVendor: Remote Corp\nTotal: $750.00"
    mock_response.raise_for_status = lambda: None

    with (
        patch("invoiceflow.engine.pipeline.httpx.AsyncClient") as mock_client_cls,
        _mock_ollama(),
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await fetch_and_process(
            "https://example.com/invoices/invoice.txt", db_session
        )

    assert result["id"] is not None
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_fetch_and_process_unsupported_type(db_session):
    """HTTP fetch rejects unsupported file types."""
    with pytest.raises(ValueError, match="Unsupported"):
        await fetch_and_process(
            "https://example.com/file.docx", db_session, filename="doc.docx"
        )


# --- get_pipeline_status tests ---


@pytest.mark.asyncio
async def test_pipeline_status_empty(db_session):
    """Pipeline status on empty DB returns zeroes."""
    status = await get_pipeline_status(db_session)
    assert status["total_invoices"] == 0
    assert status["by_status"]["pending"] == 0
    assert status["duplicates_detected"] == 0
    assert "ollama_model" in status
    assert "supported_formats" in status


@pytest.mark.asyncio
async def test_pipeline_status_with_data(db_session):
    """Pipeline status reflects actual invoice data."""
    db_session.add(Invoice(vendor_name="A", total_amount=100, status="pending"))
    db_session.add(Invoice(vendor_name="B", total_amount=200, status="approved"))
    db_session.add(Invoice(vendor_name="C", total_amount=300, status="approved"))
    db_session.add(Invoice(vendor_name="D", total_amount=400, status="rejected"))
    db_session.add(Invoice(vendor_name="E", total_amount=500, status="pending", duplicate_of_id=1))
    await db_session.commit()

    status = await get_pipeline_status(db_session)
    assert status["total_invoices"] == 5
    assert status["by_status"]["pending"] == 2
    assert status["by_status"]["approved"] == 2
    assert status["by_status"]["rejected"] == 1
    assert status["duplicates_detected"] == 1


# --- API route integration tests ---


def test_pipeline_process_endpoint(client):
    """Pipeline process endpoint via API."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Invoice #API-001\nVendor: API Corp\nTotal: $300.00")
        f.flush()
        txt_path = f.name

    with _mock_ollama():
        resp = client.post("/api/invoices/pipeline/process", json={"file_path": txt_path})

    assert resp.status_code == 201
    data = resp.json()
    assert data["invoice_number"] == "INV-PIPE-001"
    assert data["vendor_name"] == "Pipeline Test Corp"


def test_pipeline_batch_endpoint(client):
    """Pipeline batch endpoint processes directory via API."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(2):
            Path(tmpdir, f"inv_{i}.txt").write_text(f"Invoice {i}")

        with _mock_ollama():
            resp = client.post(
                "/api/invoices/pipeline/batch", json={"directory": tmpdir}
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_processed"] == 2
    assert data["successful"] == 2
    assert data["failed"] == 0


def test_pipeline_batch_bad_directory(client):
    """Pipeline batch endpoint rejects invalid directory."""
    resp = client.post(
        "/api/invoices/pipeline/batch", json={"directory": "/nonexistent/dir"}
    )
    assert resp.status_code == 400


def test_pipeline_status_endpoint(client):
    """Pipeline status endpoint returns stats."""
    resp = client.get("/api/invoices/pipeline/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_invoices" in data
    assert "by_status" in data
    assert "ollama_model" in data
    assert "supported_formats" in data


def test_pipeline_process_file_not_found(client):
    """Pipeline process endpoint returns 404 for missing file."""
    resp = client.post(
        "/api/invoices/pipeline/process",
        json={"file_path": "/nonexistent/invoice.pdf"},
    )
    assert resp.status_code == 404


def test_pipeline_process_unsupported_type(client):
    """Pipeline process endpoint returns 400 for unsupported type."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(b"fake")
        f.flush()

    resp = client.post(
        "/api/invoices/pipeline/process", json={"file_path": f.name}
    )
    assert resp.status_code == 400
