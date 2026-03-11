"""Tests for invoice routes — reprocess, email-ingest with results, and webhook."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch


def test_reprocess_invoice_not_found(client):
    """Reprocess nonexistent invoice returns 404."""
    resp = client.post("/api/invoices/99999/reprocess")
    assert resp.status_code == 404


def test_reprocess_invoice_no_file_path(client, sample_invoice_data):
    """Reprocess invoice without file_path returns 400."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.post(f"/api/invoices/{inv_id}/reprocess")
    assert resp.status_code == 400
    assert "no source file" in resp.json()["detail"].lower()


def test_reprocess_invoice_file_missing(client):
    """Reprocess invoice where file no longer exists returns 400."""
    from unittest.mock import AsyncMock, patch

    mock_extracted = {
        "invoice_number": "RE-001",
        "vendor_name": "Reprocess Corp",
        "total_amount": 100.0,
        "line_items": [],
        "raw_text": "test",
        "file_hash": "abc123",
    }

    with patch(
        "invoiceflow.routes.invoices.extract_invoice_data",
        new_callable=AsyncMock,
        return_value=mock_extracted,
    ):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Invoice content")
            f.flush()
            tmp_path = f.name

        with open(tmp_path, "rb") as upload_f:
            resp = client.post(
                "/api/invoices/upload",
                files={"file": ("reprocess_test.txt", upload_f, "text/plain")},
            )

    assert resp.status_code == 201
    inv_id = resp.json()["id"]
    file_path = resp.json()["file_path"]

    # Delete the source file
    Path(file_path).unlink(missing_ok=True)

    resp = client.post(f"/api/invoices/{inv_id}/reprocess")
    assert resp.status_code == 400
    assert "no longer exists" in resp.json()["detail"]


def test_reprocess_invoice_success(client):
    """Reprocess invoice successfully re-extracts data."""
    mock_extracted = {
        "invoice_number": "RE-002",
        "vendor_name": "First Corp",
        "total_amount": 100.0,
        "line_items": [{"description": "Item A", "quantity": 1, "amount": 100.0}],
        "raw_text": "original text",
        "file_hash": "hash1",
    }

    with patch(
        "invoiceflow.routes.invoices.extract_invoice_data",
        new_callable=AsyncMock,
        return_value=mock_extracted,
    ):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Invoice content for reprocess")
            f.flush()
            tmp_path = f.name

        with open(tmp_path, "rb") as upload_f:
            resp = client.post(
                "/api/invoices/upload",
                files={"file": ("reprocess_ok.txt", upload_f, "text/plain")},
            )

    assert resp.status_code == 201
    inv_id = resp.json()["id"]

    # Now reprocess with updated extraction
    mock_reextracted = {
        "invoice_number": "RE-002-UPDATED",
        "vendor_name": "Updated Corp",
        "total_amount": 200.0,
        "line_items": [
            {"description": "New Item", "quantity": 2, "unit_price": 100.0, "amount": 200.0}
        ],
        "raw_text": "updated text",
        "file_hash": "hash2",
    }

    with patch(
        "invoiceflow.routes.invoices.extract_invoice_data",
        new_callable=AsyncMock,
        return_value=mock_reextracted,
    ):
        resp = client.post(f"/api/invoices/{inv_id}/reprocess")

    assert resp.status_code == 200
    data = resp.json()
    assert data["invoice_number"] == "RE-002-UPDATED"
    assert data["vendor_name"] == "Updated Corp"
    assert data["total_amount"] == 200.0
    assert len(data["line_items"]) == 1


def test_reprocess_extraction_failure(client):
    """Reprocess with extraction failure returns 502."""
    mock_extracted = {
        "invoice_number": "RE-003",
        "vendor_name": "Fail Corp",
        "total_amount": 50.0,
        "line_items": [],
        "raw_text": "test",
        "file_hash": "abc",
    }

    with patch(
        "invoiceflow.routes.invoices.extract_invoice_data",
        new_callable=AsyncMock,
        return_value=mock_extracted,
    ):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Invoice fail test")
            f.flush()
            tmp_path = f.name

        with open(tmp_path, "rb") as upload_f:
            resp = client.post(
                "/api/invoices/upload",
                files={"file": ("reprocess_fail.txt", upload_f, "text/plain")},
            )

    assert resp.status_code == 201
    inv_id = resp.json()["id"]

    with patch(
        "invoiceflow.routes.invoices.extract_invoice_data",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Ollama is down"),
    ):
        resp = client.post(f"/api/invoices/{inv_id}/reprocess")

    assert resp.status_code == 502
    assert "Re-extraction failed" in resp.json()["detail"]


def test_email_ingest_with_results(client):
    """Email ingest endpoint with successful and failed results."""
    mock_results = [
        {
            "id": 1,
            "invoice_number": "EMAIL-001",
            "vendor_name": "Email Vendor",
            "total_amount": 500.0,
            "status": "pending",
            "category": "General Expense",
        },
        {"file": "bad_attachment.pdf", "error": "Extraction failed"},
    ]

    with patch(
        "invoiceflow.engine.email_ingestor.ingest_from_mailbox",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        resp = client.post("/api/invoices/email-ingest", json={
            "host": "mail.example.com",
            "user": "test@example.com",
            "password": "secret",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_processed"] == 2
    assert data["successful"] == 1
    assert data["failed"] == 1
