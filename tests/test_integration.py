"""Integration tests for the InvoiceFlow API.

Tests the full API endpoints with a real SQLite database.
"""

import tempfile
from pathlib import Path


def test_create_invoice(client, sample_invoice_data):
    """Create an invoice via API and verify response."""
    resp = client.post("/api/invoices", json=sample_invoice_data)
    assert resp.status_code == 201
    data = resp.json()
    assert data["invoice_number"] == "INV-2026-001"
    assert data["vendor_name"] == "Acme Office Supplies"
    assert data["total_amount"] == 486.00
    assert data["status"] == "pending"
    assert data["category"] == "Office Supplies"
    assert len(data["line_items"]) == 2


def test_list_invoices(client, sample_invoice_data):
    """List invoices returns created invoices."""
    client.post("/api/invoices", json=sample_invoice_data)
    resp = client.get("/api/invoices")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["invoices"]) >= 1


def test_get_invoice_by_id(client, sample_invoice_data):
    """Get single invoice by ID."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.get(f"/api/invoices/{inv_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == inv_id


def test_get_invoice_not_found(client):
    """Get nonexistent invoice returns 404."""
    resp = client.get("/api/invoices/99999")
    assert resp.status_code == 404


def test_update_invoice_status(client, sample_invoice_data):
    """Approve an invoice via status update."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.patch(f"/api/invoices/{inv_id}/status", json={"status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_update_invoice_invalid_status(client, sample_invoice_data):
    """Invalid status value returns 422."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.patch(f"/api/invoices/{inv_id}/status", json={"status": "invalid"})
    assert resp.status_code == 422


def test_validate_invoice_no_po(client, sample_invoice_data):
    """Validate invoice without matching PO."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.post(f"/api/invoices/{inv_id}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert any("not found" in d for d in data["discrepancies"])


def test_validate_invoice_with_matching_po(client, sample_invoice_data, sample_po_data):
    """Validate invoice against matching PO — should pass."""
    client.post("/api/purchase-orders", json=sample_po_data)
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.post(f"/api/invoices/{inv_id}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["po_number"] == "PO-1001"


def test_validate_invoice_amount_mismatch(client, sample_invoice_data, sample_po_data):
    """Validate invoice against PO with different amount — should flag discrepancy."""
    po_data = {**sample_po_data, "total_amount": 999.99}
    client.post("/api/purchase-orders", json=po_data)

    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.post(f"/api/invoices/{inv_id}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert any("Amount mismatch" in d for d in data["discrepancies"])


def test_check_duplicates(client, sample_invoice_data):
    """Duplicate check finds identical invoices."""
    client.post("/api/invoices", json=sample_invoice_data)
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.post(f"/api/invoices/{inv_id}/duplicates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_duplicate"] is True
    assert len(data["matches"]) >= 1
    assert data["matches"][0]["similarity_score"] >= 85.0


def test_create_purchase_order(client, sample_po_data):
    """Create PO via API."""
    resp = client.post("/api/purchase-orders", json=sample_po_data)
    assert resp.status_code == 201
    data = resp.json()
    assert data["po_number"] == "PO-1001"
    assert data["status"] == "open"


def test_create_duplicate_po(client, sample_po_data):
    """Duplicate PO number returns 409."""
    client.post("/api/purchase-orders", json=sample_po_data)
    resp = client.post("/api/purchase-orders", json=sample_po_data)
    assert resp.status_code == 409


def test_list_purchase_orders(client, sample_po_data):
    """List POs returns created POs."""
    client.post("/api/purchase-orders", json=sample_po_data)
    resp = client.get("/api/purchase-orders")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


def test_export_csv(client, sample_invoice_data):
    """Export invoices to CSV."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]
    client.patch(f"/api/invoices/{inv_id}/status", json={"status": "approved"})

    resp = client.post("/api/invoices/export", json={"format": "csv"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["format"] == "csv"
    assert data["invoice_count"] == 1
    assert data["file_path"].endswith(".csv")


def test_export_iif(client, sample_invoice_data):
    """Export invoices to QuickBooks IIF format."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]
    client.patch(f"/api/invoices/{inv_id}/status", json={"status": "approved"})

    resp = client.post("/api/invoices/export", json={"format": "iif"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["format"] == "iif"
    assert data["file_path"].endswith(".iif")


def test_filter_invoices_by_status(client, sample_invoice_data):
    """Filter invoices by status."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]
    client.patch(f"/api/invoices/{inv_id}/status", json={"status": "approved"})

    resp = client.get("/api/invoices?status=approved")
    assert resp.status_code == 200
    data = resp.json()
    assert all(inv["status"] == "approved" for inv in data["invoices"])


def test_filter_invoices_by_vendor(client, sample_invoice_data):
    """Filter invoices by vendor name."""
    client.post("/api/invoices", json=sample_invoice_data)

    resp = client.get("/api/invoices?vendor=Acme")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


def test_watch_folder_status(client):
    """Watch folder status endpoint returns config."""
    resp = client.get("/api/invoices/watch-folder/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "watch_dir" in data
    assert ".pdf" in data["supported_extensions"]
    assert data["active"] is True


def test_ingest_nonexistent_file(client):
    """Ingest endpoint rejects non-existent file."""
    resp = client.post("/api/invoices/ingest", json={"file_path": "/nonexistent/file.pdf"})
    assert resp.status_code == 400


def test_ingest_unsupported_file(client):
    """Ingest endpoint rejects unsupported file type."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(b"fake")
        f.flush()
    resp = client.post("/api/invoices/ingest", json={"file_path": f.name})
    assert resp.status_code == 400


def test_upload_invoice_file(client):
    """Upload an invoice text file via the upload endpoint."""
    content = b"Invoice #UPLOAD-001\nVendor: Upload Corp\nTotal: $250.00"
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = f.name

    from unittest.mock import AsyncMock, patch

    mock_response = {
        "invoice_number": "UPLOAD-001",
        "vendor_name": "Upload Corp",
        "total_amount": 250.0,
        "line_items": [{"description": "Service", "quantity": 1, "amount": 250.0}],
    }

    with patch(
        "invoiceflow.routes.invoices.extract_invoice_data",
        new_callable=AsyncMock,
        return_value={**mock_response, "raw_text": "test", "file_hash": "abc123"},
    ):
        with open(tmp_path, "rb") as upload_f:
            resp = client.post(
                "/api/invoices/upload",
                files={"file": ("invoice.txt", upload_f, "text/plain")},
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["invoice_number"] == "UPLOAD-001"
    assert data["vendor_name"] == "Upload Corp"
    assert data["status"] == "pending"
    assert len(data["line_items"]) == 1


def test_upload_invoice_no_filename(client):
    """Upload with no filename returns error."""
    resp = client.post(
        "/api/invoices/upload",
        files={"file": ("", b"content", "text/plain")},
    )
    assert resp.status_code in (400, 422)


def test_validate_invoice_no_po_number(client):
    """Validate an invoice that has no PO number."""
    invoice_data = {
        "invoice_number": "INV-NOPO-001",
        "vendor_name": "No PO Vendor",
        "total_amount": 100.0,
        "line_items": [],
    }
    create_resp = client.post("/api/invoices", json=invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.post(f"/api/invoices/{inv_id}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert any("No PO number" in d for d in data["discrepancies"])


def test_validate_invoice_vendor_mismatch(client):
    """Validate invoice with vendor name mismatch."""
    client.post("/api/purchase-orders", json={
        "po_number": "PO-VENDOR",
        "vendor_name": "Correct Vendor",
        "total_amount": 500.0,
    })
    create_resp = client.post("/api/invoices", json={
        "invoice_number": "INV-VENDOR",
        "vendor_name": "Wrong Vendor",
        "total_amount": 500.0,
        "po_number": "PO-VENDOR",
        "line_items": [],
    })
    inv_id = create_resp.json()["id"]

    resp = client.post(f"/api/invoices/{inv_id}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert any("Vendor mismatch" in d for d in data["discrepancies"])


def test_export_csv_specific_ids(client, sample_invoice_data):
    """Export specific invoices by ID to CSV."""
    create_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = create_resp.json()["id"]

    resp = client.post("/api/invoices/export", json={"format": "csv", "invoice_ids": [inv_id]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["format"] == "csv"
    file_path = Path(data["file_path"])
    assert file_path.exists()
    content = file_path.read_text()
    assert "INV-2026-001" in content


def test_get_purchase_order_by_id(client, sample_po_data):
    """Get single PO by ID."""
    create_resp = client.post("/api/purchase-orders", json=sample_po_data)
    po_id = create_resp.json()["id"]

    resp = client.get(f"/api/purchase-orders/{po_id}")
    assert resp.status_code == 200
    assert resp.json()["po_number"] == "PO-1001"


def test_get_purchase_order_not_found(client):
    """Get nonexistent PO returns 404."""
    resp = client.get("/api/purchase-orders/99999")
    assert resp.status_code == 404


def test_validate_invoice_not_found(client):
    """Validate nonexistent invoice returns 404."""
    resp = client.post("/api/invoices/99999/validate")
    assert resp.status_code == 404


def test_check_duplicates_not_found(client):
    """Duplicate check on nonexistent invoice returns 404."""
    resp = client.post("/api/invoices/99999/duplicates")
    assert resp.status_code == 404


def test_update_status_not_found(client):
    """Status update on nonexistent invoice returns 404."""
    resp = client.patch("/api/invoices/99999/status", json={"status": "approved"})
    assert resp.status_code == 404


def test_export_no_approved_invoices(client):
    """Export with no approved invoices returns empty export."""
    resp = client.post("/api/invoices/export", json={"format": "csv"})
    assert resp.status_code == 200
    assert resp.json()["invoice_count"] == 0


def test_list_purchase_orders_filter_by_status(client, sample_po_data):
    """Filter POs by status."""
    client.post("/api/purchase-orders", json=sample_po_data)
    resp = client.get("/api/purchase-orders?status=open")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(po["status"] == "open" for po in data["purchase_orders"])
