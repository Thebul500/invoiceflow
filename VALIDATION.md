# InvoiceFlow — Real-World Validation

**Date**: 2026-03-11
**Environment**: Docker Compose (app + PostgreSQL 16)
**Host**: Linux 6.17.0-14-generic, Docker 29.2.1, Compose v2.39.2
**Database**: PostgreSQL 16-alpine via `postgresql+asyncpg`
**App Image**: `invoiceflow-app` (Python 3.12-slim, multi-stage build)

---

## Stack Startup

```
$ docker compose up --build -d

 Container invoiceflow-postgres-1  Created
 Container invoiceflow-app-1       Created
 Container invoiceflow-postgres-1  Started
 Container invoiceflow-postgres-1  Healthy
 Container invoiceflow-app-1       Started
```

**Fix required**: Added `asyncpg>=0.29` to `pyproject.toml` — the PostgreSQL async driver was missing from dependencies. After rebuild, app started cleanly.

```
app-1  | INFO:     Started server process [1]
app-1  | INFO:     Waiting for application startup.
app-1  | INFO:     Application startup complete.
app-1  | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

## Test Results

### 1. Health Check — PASS
**Timestamp**: 2026-03-11T04:54:31Z

```json
GET /health → 200
{
    "status": "healthy",
    "version": "0.1.0",
    "timestamp": "2026-03-11T04:54:31.845049Z"
}
```

### 2. Readiness Probe — PASS
**Timestamp**: 2026-03-11T04:54:31Z

```json
GET /ready → 200
{"status": "ready"}
```

### 3. OpenAPI Schema — PASS
**Timestamp**: 2026-03-11T04:54:31Z

20 endpoints discovered:
```
GET  /health
GET  /ready
POST /api/invoices/upload
POST /api/invoices
GET  /api/invoices
GET  /api/invoices/{invoice_id}
PATCH /api/invoices/{invoice_id}/status
POST /api/invoices/{invoice_id}/validate
POST /api/invoices/{invoice_id}/duplicates
POST /api/invoices/export
POST /api/invoices/ingest
POST /api/invoices/fetch-url
GET  /api/invoices/watch-folder/status
POST /api/invoices/pipeline/process
POST /api/invoices/pipeline/batch
GET  /api/invoices/pipeline/status
POST /api/invoices/email-ingest
POST /api/purchase-orders
GET  /api/purchase-orders
GET  /api/purchase-orders/{po_id}
```

### 4. Create Purchase Order — PASS
**Timestamp**: 2026-03-11T04:54:38Z

```json
POST /api/purchase-orders → 200
{
    "po_number": "PO-2026-001",
    "vendor_name": "Acme Office Supplies",
    "total_amount": 1500.0,
    "description": "Office supplies for Q1 2026",
    "id": 1,
    "status": "open",
    "created_at": "2026-03-11T04:54:38.609318"
}
```

### 5. Create Second Purchase Order — PASS
**Timestamp**: 2026-03-11T04:54:40Z

```json
POST /api/purchase-orders → 200
{
    "po_number": "PO-2026-002",
    "vendor_name": "TechParts Inc",
    "total_amount": 3200.0,
    "id": 2,
    "status": "open"
}
```

### 6. List Purchase Orders — PASS
**Timestamp**: 2026-03-11T04:54:41Z

```json
GET /api/purchase-orders → 200
{"purchase_orders": [...], "total": 2}
```

### 7. Get Single Purchase Order — PASS
**Timestamp**: 2026-03-11T04:54:41Z

```json
GET /api/purchase-orders/1 → 200
{"po_number": "PO-2026-001", "vendor_name": "Acme Office Supplies", ...}
```

### 8. Duplicate PO Rejection — PASS
**Timestamp**: 2026-03-11T04:54:41Z

```json
POST /api/purchase-orders → 409
{"detail": "PO PO-2026-001 already exists"}
```

### 9. Create Invoice with Line Items — PASS
**Timestamp**: 2026-03-11T04:54:49Z

```json
POST /api/invoices → 200
{
    "invoice_number": "INV-2026-0001",
    "vendor_name": "Acme Office Supplies",
    "total_amount": 1500.0,
    "po_number": "PO-2026-001",
    "category": "Office Supplies",
    "id": 1,
    "status": "pending",
    "line_items": [
        {"description": "Printer Paper (10 reams)", "quantity": 10.0, "unit_price": 45.0, "amount": 450.0},
        {"description": "Toner Cartridges", "quantity": 5.0, "unit_price": 120.0, "amount": 600.0},
        {"description": "Desk Organizers", "quantity": 7.0, "unit_price": 50.0, "amount": 350.0}
    ]
}
```

Auto-categorization assigned: `"category": "Office Supplies"`

### 10. Create Second Invoice — PASS
**Timestamp**: 2026-03-11T04:54:52Z

```json
POST /api/invoices → 200
{
    "invoice_number": "INV-2026-0002",
    "vendor_name": "TechParts Inc",
    "total_amount": 3200.0,
    "category": "Raw Materials",
    "id": 2,
    "status": "pending",
    "line_items": [
        {"description": "SSD 1TB NVMe", "quantity": 4.0, "amount": 2000.0},
        {"description": "ECC RAM 32GB", "quantity": 4.0, "amount": 1000.0}
    ]
}
```

Auto-categorization assigned: `"category": "Raw Materials"`

### 11. List Invoices — PASS
**Timestamp**: 2026-03-11T04:54:53Z

```json
GET /api/invoices → 200
{"invoices": [...], "total": 2}
```

### 12. Get Single Invoice — PASS
**Timestamp**: 2026-03-11T04:54:53Z

```json
GET /api/invoices/1 → 200
{"invoice_number": "INV-2026-0001", "vendor_name": "Acme Office Supplies", ...}
```

### 13. Filter by Vendor — PASS
**Timestamp**: 2026-03-11T04:54:53Z

```json
GET /api/invoices?vendor=TechParts → 200
{"total": 1}   # Only TechParts invoice returned
```

### 14. Filter by Status — PASS
**Timestamp**: 2026-03-11T04:54:53Z

```json
GET /api/invoices?status=pending → 200
{"total": 2}   # Both invoices pending at this point
```

### 15. Validate Invoice Against PO (Matching) — PASS
**Timestamp**: 2026-03-11T04:55:01Z

```json
POST /api/invoices/1/validate → 200
{
    "valid": true,
    "discrepancies": [],
    "po_number": "PO-2026-001",
    "po_amount": 1500.0,
    "invoice_amount": 1500.0
}
```

### 16. Validate Invoice 2 Against PO — PASS
**Timestamp**: 2026-03-11T04:55:01Z

```json
POST /api/invoices/2/validate → 200
{
    "valid": true,
    "discrepancies": [],
    "po_number": "PO-2026-002",
    "po_amount": 3200.0,
    "invoice_amount": 3200.0
}
```

### 17. Duplicate Check (No Duplicates) — PASS
**Timestamp**: 2026-03-11T04:55:03Z

```json
POST /api/invoices/1/duplicates → 200
{"is_duplicate": false, "matches": []}
```

### 18. Create Near-Duplicate Invoice — PASS
**Timestamp**: 2026-03-11T04:55:07Z

Created invoice with same vendor, amount, and line items but different invoice number (`INV-2026-0001a`).

```json
POST /api/invoices → 200
{
    "id": 3,
    "invoice_number": "INV-2026-0001a",
    "duplicate_of_id": 1     # Auto-detected as duplicate on creation!
}
```

### 19. Duplicate Check (Confirmed) — PASS
**Timestamp**: 2026-03-11T04:55:07Z

```json
POST /api/invoices/3/duplicates → 200
{
    "is_duplicate": true,
    "matches": [
        {
            "invoice_id": 1,
            "invoice_number": "INV-2026-0001",
            "vendor_name": "Acme Office Supplies",
            "total_amount": 1500.0,
            "similarity_score": 98.5
        }
    ]
}
```

Fuzzy matching detected 98.5% similarity — correctly flagged.

### 20. Approve Invoice — PASS
**Timestamp**: 2026-03-11T04:55:15Z

```json
PATCH /api/invoices/1/status → 200
{"status": "approved", "validation_notes": "Valid"}
```

### 21. Reject Duplicate Invoice — PASS
**Timestamp**: 2026-03-11T04:55:15Z

```json
PATCH /api/invoices/3/status → 200
{"status": "rejected", "duplicate_of_id": 1}
```

### 22. Filter by Status (Approved) — PASS
**Timestamp**: 2026-03-11T04:55:15Z

```
GET /api/invoices?status=approved → 200
Total approved: 1 (INV-2026-0001)
```

### 23. Export to CSV — PASS
**Timestamp**: 2026-03-11T04:55:20Z

```json
POST /api/invoices/export → 200
{
    "file_path": "/root/.invoiceflow/exports/invoices_20260311_045520.csv",
    "format": "csv",
    "invoice_count": 1
}
```

Exports only approved invoices.

### 24. Export to IIF (QuickBooks) — PASS
**Timestamp**: 2026-03-11T04:55:20Z

```json
POST /api/invoices/export → 200
{
    "file_path": "/root/.invoiceflow/exports/invoices_20260311_045520.iif",
    "format": "iif",
    "invoice_count": 1
}
```

### 25. Watch Folder Status — PASS
**Timestamp**: 2026-03-11T04:55:22Z

```json
GET /api/invoices/watch-folder/status → 200
{
    "watch_dir": "/root/.invoiceflow/watch",
    "supported_extensions": [".bmp", ".eml", ".jpeg", ".jpg", ".pdf", ".png", ".tiff", ".txt", ".webp"],
    "active": true
}
```

### 26. Pipeline Status — PASS
**Timestamp**: 2026-03-11T04:55:22Z

```json
GET /api/invoices/pipeline/status → 200
{
    "total_invoices": 3,
    "by_status": {"pending": 1, "approved": 1, "rejected": 1, "exported": 0},
    "duplicates_detected": 1,
    "ollama_model": "qwen2.5:14b",
    "ollama_url": "http://10.0.3.144:11434"
}
```

### 27. Create Invoice with Amount Mismatch — PASS
**Timestamp**: 2026-03-11T04:55:25Z

```json
POST /api/invoices → 200
{
    "id": 4,
    "invoice_number": "INV-2026-0003",
    "total_amount": 1950.0,
    "po_number": "PO-2026-001"
}
```

### 28. Validate Mismatched Invoice — PASS
**Timestamp**: 2026-03-11T04:55:25Z

```json
POST /api/invoices/4/validate → 200
{
    "valid": false,
    "discrepancies": [
        "Amount mismatch: invoice=$1950.00, PO=$1500.00 (diff=$450.00)"
    ],
    "po_number": "PO-2026-001",
    "po_amount": 1500.0,
    "invoice_amount": 1950.0
}
```

Correctly flagged $450.00 discrepancy between invoice and PO.

### 29. Non-Existent Invoice — PASS
**Timestamp**: 2026-03-11T04:55:28Z

```
GET /api/invoices/999 → 404
{"detail": "Invoice not found"}
```

### 30. Non-Existent Purchase Order — PASS
**Timestamp**: 2026-03-11T04:55:28Z

```
GET /api/purchase-orders/999 → 404
{"detail": "Purchase order not found"}
```

### 31. Invalid Status Value — PASS
**Timestamp**: 2026-03-11T04:55:28Z

```
PATCH /api/invoices/1/status {"status": "invalid_status"} → 422
Pattern validation: ^(pending|approved|rejected|exported)$
```

### 32. Export Status Transition — PASS
**Timestamp**: 2026-03-11T04:55:30Z

```json
PATCH /api/invoices/1/status → 200
{"invoice_number": "INV-2026-0001", "status": "exported"}
```

Full workflow: pending → approved → exported

### 33. Final Pipeline Status — PASS
**Timestamp**: 2026-03-11T04:55:30Z

```json
GET /api/invoices/pipeline/status → 200
{
    "total_invoices": 4,
    "by_status": {"pending": 2, "approved": 0, "rejected": 1, "exported": 1},
    "duplicates_detected": 2
}
```

---

## Resource Usage

| Container | CPU | Memory | Network I/O |
|-----------|-----|--------|-------------|
| invoiceflow-app-1 | 0.15% | 74.62 MiB | 66 KB / 94.5 KB |
| invoiceflow-postgres-1 | 0.00% | 29.27 MiB | 49.4 KB / 42.7 KB |

Total stack memory: ~104 MiB

---

## Summary

| Category | Tests | Result |
|----------|-------|--------|
| Health/Readiness | 2 | PASS |
| OpenAPI Schema | 1 | PASS |
| Purchase Order CRUD | 4 | PASS |
| Invoice CRUD | 4 | PASS |
| Filtering (vendor, status) | 2 | PASS |
| PO Validation (match) | 2 | PASS |
| PO Validation (mismatch) | 1 | PASS |
| Duplicate Detection | 3 | PASS |
| Status Workflow | 3 | PASS |
| Export (CSV + IIF) | 2 | PASS |
| Watch Folder | 1 | PASS |
| Pipeline Status | 2 | PASS |
| Error Handling (404, 409, 422) | 3 | PASS |
| **Total** | **30** | **30/30 PASS** |

### Key Findings

1. **Missing dependency**: `asyncpg` was not listed in `pyproject.toml` despite docker-compose using PostgreSQL. Fixed by adding `asyncpg>=0.29`.
2. **Auto-categorization works**: Invoices are automatically categorized (e.g., "Office Supplies", "Raw Materials") based on line item descriptions.
3. **Duplicate detection works**: Fuzzy matching correctly identified a near-duplicate invoice at 98.5% similarity and auto-linked `duplicate_of_id` on creation.
4. **PO validation works**: Both matching amounts (valid) and mismatched amounts (flagged with discrepancy details) handled correctly.
5. **Full status workflow**: pending → approved → exported lifecycle confirmed. Rejected duplicates handled.
6. **Export**: Both CSV and QuickBooks IIF formats generate files. Only approved/exported invoices are included.
7. **Lightweight**: Full stack runs in ~104 MiB total (app 75 MiB + PostgreSQL 29 MiB).

### Limitations

- **File upload not tested**: Requires multipart form data with actual PDF/image files — not tested in this API-only validation.
- **Ollama extraction not tested**: LLM-based field extraction requires network access to the Ollama server (10.0.3.144) from inside the container. The container network may not route to the host network.
- **Email ingestion not tested**: Requires IMAP server configuration.
- **Webhook notifications not tested**: No webhook endpoint configured.
