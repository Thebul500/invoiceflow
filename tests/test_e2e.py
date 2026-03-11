"""End-to-end tests — full invoice lifecycle from creation to export."""

from pathlib import Path


def test_full_invoice_lifecycle(client, sample_invoice_data, sample_po_data):
    """Test the complete invoice workflow:
    1. Create PO
    2. Submit invoice
    3. Validate against PO
    4. Approve
    5. Export to CSV
    6. Verify export file exists
    """
    po_resp = client.post("/api/purchase-orders", json=sample_po_data)
    assert po_resp.status_code == 201

    inv_resp = client.post("/api/invoices", json=sample_invoice_data)
    assert inv_resp.status_code == 201
    inv_id = inv_resp.json()["id"]
    assert inv_resp.json()["status"] == "pending"
    assert inv_resp.json()["category"] == "Office Supplies"

    val_resp = client.post(f"/api/invoices/{inv_id}/validate")
    assert val_resp.status_code == 200
    assert val_resp.json()["valid"] is True

    approve_resp = client.patch(f"/api/invoices/{inv_id}/status", json={"status": "approved"})
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    export_resp = client.post("/api/invoices/export", json={"format": "csv"})
    assert export_resp.status_code == 200
    export_data = export_resp.json()
    assert export_data["invoice_count"] == 1

    export_path = Path(export_data["file_path"])
    assert export_path.exists()
    csv_content = export_path.read_text()
    assert "INV-2026-001" in csv_content
    assert "Acme Office Supplies" in csv_content
    assert "Copy paper" in csv_content


def test_duplicate_detection_lifecycle(client, sample_invoice_data):
    """Test duplicate detection across the full workflow."""
    resp1 = client.post("/api/invoices", json=sample_invoice_data)
    assert resp1.status_code == 201
    id1 = resp1.json()["id"]

    resp2 = client.post("/api/invoices", json=sample_invoice_data)
    assert resp2.status_code == 201
    id2 = resp2.json()["id"]
    assert resp2.json()["duplicate_of_id"] == id1

    dup_resp = client.post(f"/api/invoices/{id2}/duplicates")
    assert dup_resp.status_code == 200
    assert dup_resp.json()["is_duplicate"] is True


def test_po_validation_mismatch_lifecycle(client, sample_invoice_data):
    """Test invoice rejected due to PO amount mismatch."""
    po_data = {
        "po_number": "PO-1001",
        "vendor_name": "Acme Office Supplies",
        "total_amount": 200.00,
        "description": "Partial order",
    }
    client.post("/api/purchase-orders", json=po_data)

    inv_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = inv_resp.json()["id"]

    val_resp = client.post(f"/api/invoices/{inv_id}/validate")
    assert val_resp.json()["valid"] is False
    assert any("Amount mismatch" in d for d in val_resp.json()["discrepancies"])

    reject_resp = client.patch(f"/api/invoices/{inv_id}/status", json={"status": "rejected"})
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"


def test_iif_export_format(client, sample_invoice_data):
    """Test QuickBooks IIF export produces correct format."""
    inv_resp = client.post("/api/invoices", json=sample_invoice_data)
    inv_id = inv_resp.json()["id"]
    client.patch(f"/api/invoices/{inv_id}/status", json={"status": "approved"})

    export_resp = client.post("/api/invoices/export", json={"format": "iif"})
    assert export_resp.status_code == 200

    iif_path = Path(export_resp.json()["file_path"])
    assert iif_path.exists()
    content = iif_path.read_text()
    assert "!TRNS" in content
    assert "!SPL" in content
    assert "ENDTRNS" in content
    assert "BILL" in content
    assert "Acme Office Supplies" in content


def test_multiple_invoices_export(client):
    """Export multiple invoices at once."""
    ids = []
    for i in range(3):
        data = {
            "invoice_number": f"INV-MULTI-{i}",
            "vendor_name": f"Vendor {i}",
            "total_amount": 100.0 * (i + 1),
            "line_items": [{"description": f"Item {i}", "quantity": 1, "amount": 100.0 * (i + 1)}],
        }
        resp = client.post("/api/invoices", json=data)
        inv_id = resp.json()["id"]
        client.patch(f"/api/invoices/{inv_id}/status", json={"status": "approved"})
        ids.append(inv_id)

    export_resp = client.post("/api/invoices/export", json={"format": "csv", "invoice_ids": ids})
    assert export_resp.status_code == 200
    assert export_resp.json()["invoice_count"] == 3
