# InvoiceFlow — Project Plan

## Overview

InvoiceFlow is an AI-powered invoice processing pipeline that automates the extraction, validation, and approval of invoices. It ingests documents (PDF, image, email), uses an LLM to extract structured data, validates against purchase orders, detects duplicates, and exports to accounting formats — replacing manual data entry with an intelligent, auditable workflow.

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ REST API │  │ Watch Folder │  │ CLI (invoiceflow-cli)  │ │
│  │ /invoices│  │  Observer    │  │                        │ │
│  └────┬─────┘  └──────┬───────┘  └───────────┬────────────┘ │
│       │               │                      │               │
│       └───────────────┼──────────────────────┘               │
│                       ▼                                      │
│              ┌────────────────┐                               │
│              │ Ingestion Layer│                               │
│              │ (PDF/IMG/Email)│                               │
│              └───────┬────────┘                               │
│                      ▼                                       │
│              ┌────────────────┐     ┌──────────────────┐     │
│              │  LLM Extractor │────▶│  Ollama (local)  │     │
│              │  (structured)  │◀────│  qwen2.5:14b     │     │
│              └───────┬────────┘     └──────────────────┘     │
│                      ▼                                       │
│       ┌──────────────────────────────┐                       │
│       │      Processing Pipeline     │                       │
│       │  ┌────────────────────────┐  │                       │
│       │  │ Duplicate Detection    │  │                       │
│       │  │ (fuzzy matching)       │  │                       │
│       │  ├────────────────────────┤  │                       │
│       │  │ PO Validation          │  │                       │
│       │  │ (amount/vendor match)  │  │                       │
│       │  ├────────────────────────┤  │                       │
│       │  │ Expense Categorization │  │                       │
│       │  │ (LLM-assisted)         │  │                       │
│       │  ├────────────────────────┤  │                       │
│       │  │ Discrepancy Flagging   │  │                       │
│       │  └────────────────────────┘  │                       │
│       └──────────────┬───────────────┘                       │
│                      ▼                                       │
│       ┌──────────────────────────────┐                       │
│       │     Approval Workflow        │                       │
│       │  pending → approved/rejected │                       │
│       │  webhook notifications       │                       │
│       └──────────────┬───────────────┘                       │
│                      ▼                                       │
│       ┌──────────────────────────────┐                       │
│       │     Export Layer             │                       │
│       │  CSV / QuickBooks IIF       │                       │
│       └──────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │    SQLite DB   │
              │  (invoices,    │
              │   line_items,  │
              │   POs, audit)  │
              └────────────────┘
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/invoices/upload` | Upload invoice file (PDF/image) for processing |
| `GET` | `/api/v1/invoices` | List invoices with filters (status, vendor, date range) |
| `GET` | `/api/v1/invoices/{id}` | Get invoice detail with line items and flags |
| `POST` | `/api/v1/invoices/{id}/approve` | Approve an invoice |
| `POST` | `/api/v1/invoices/{id}/reject` | Reject an invoice with reason |
| `POST` | `/api/v1/invoices/{id}/reprocess` | Re-run LLM extraction on an invoice |
| `GET` | `/api/v1/invoices/{id}/export` | Export single invoice (CSV or IIF format) |
| `POST` | `/api/v1/invoices/export` | Bulk export invoices by filter |
| `GET` | `/api/v1/purchase-orders` | List purchase orders |
| `POST` | `/api/v1/purchase-orders` | Create a purchase order for validation |
| `GET` | `/api/v1/purchase-orders/{id}` | Get PO detail |
| `GET` | `/api/v1/invoices/{id}/duplicates` | Check for duplicate invoices |
| `GET` | `/api/v1/stats` | Dashboard stats (totals, flagged count, by category) |
| `GET` | `/health` | Health check (already implemented) |

### Data Model

```
Invoice
├── id: int (PK)
├── file_path: str              # original uploaded file
├── file_hash: str              # SHA-256 for dedup
├── status: enum                # pending_extraction, extracted, pending_approval,
│                               # approved, rejected, exported, error
├── vendor_name: str            # LLM-extracted
├── vendor_id: str | null       # matched vendor reference
├── invoice_number: str         # LLM-extracted
├── invoice_date: date          # LLM-extracted
├── due_date: date | null       # LLM-extracted
├── total_amount: Decimal       # LLM-extracted, validated against line items
├── currency: str               # default USD
├── po_number: str | null       # LLM-extracted, used for PO matching
├── category: str | null        # LLM-categorized expense type
├── confidence_score: float     # LLM extraction confidence (0-1)
├── raw_llm_response: text      # full LLM output for audit
├── flags: JSON                 # list of discrepancy flags
├── approved_by: str | null
├── approved_at: datetime | null
├── rejection_reason: str | null
├── created_at: datetime
├── updated_at: datetime
│
├── line_items: [LineItem]
└── matched_po: PurchaseOrder | null

LineItem
├── id: int (PK)
├── invoice_id: int (FK → Invoice)
├── description: str
├── quantity: Decimal
├── unit_price: Decimal
├── total: Decimal
├── category: str | null
├── created_at: datetime

PurchaseOrder
├── id: int (PK)
├── po_number: str (unique)
├── vendor_name: str
├── total_amount: Decimal
├── status: enum                # open, partially_fulfilled, fulfilled, closed
├── issued_date: date
├── items: JSON                 # line item expectations
├── created_at: datetime
├── updated_at: datetime

WebhookConfig
├── id: int (PK)
├── url: str                    # callback URL
├── events: JSON                # list of event types to notify on
├── active: bool
├── secret: str                 # HMAC signing secret
├── created_at: datetime
```

### Processing Pipeline (Data Flow)

1. **Ingestion**: File uploaded via API or detected in watch folder. File hash computed. Stored on disk, record created with `pending_extraction` status.
2. **Duplicate Check**: SHA-256 exact match first, then fuzzy match on (vendor + amount + date) against recent invoices. If duplicate found, flag and halt.
3. **LLM Extraction**: Invoice file sent to Ollama with a structured extraction prompt. Response parsed into vendor, line items, amounts, dates, PO number. Confidence score assigned.
4. **Validation**: If PO number found, match against PurchaseOrder table. Compare vendor name (fuzzy), total amount (tolerance threshold), line items. Generate discrepancy flags for mismatches.
5. **Categorization**: LLM classifies expense category based on vendor and line item descriptions. Categories: supplies, services, equipment, travel, software, utilities, other.
6. **Approval Routing**: Invoice enters `pending_approval` status. Webhook fired to configured endpoints. Approver can approve or reject via API.
7. **Export**: Approved invoices exported to CSV or QuickBooks IIF format on demand.

### Auth Flow

- JWT bearer tokens via `Authorization` header
- `/auth/login` returns access token (30-min expiry)
- Token contains user ID and role (admin, approver, viewer)
- Upload/approve/reject require `approver` or `admin` role
- Export and read endpoints require any authenticated role
- Watch folder processing runs as system user (no auth needed for internal pipeline)

### Deployment Architecture

- **Single container**: FastAPI app with Uvicorn workers
- **SQLite**: Embedded database, file on mounted volume (no external DB dependency for small-to-medium deployments)
- **Ollama**: External dependency on local or network Ollama instance (configurable URL)
- **Watch folder**: Mounted volume path, monitored by background task in the FastAPI lifespan
- **Webhooks**: Outbound HTTP calls via httpx async client

---

## Technology

| Technology | Role | Why |
|---|---|---|
| **FastAPI** | Web framework | Async-native, auto-generates OpenAPI docs, Pydantic validation built in. Ideal for file upload + JSON API hybrid. |
| **SQLAlchemy 2.0 (async)** | ORM / database | Async session support, Alembic migrations, works with both SQLite and PostgreSQL. Already scaffolded. |
| **SQLite (aiosqlite)** | Database | Zero-config, single-file, perfect for single-tenant invoice processing. No external database service needed. PostgreSQL available via config swap for larger deployments. |
| **Ollama** | LLM inference | Local model hosting, no API keys, privacy-preserving (invoices stay on-premises). Uses qwen2.5:14b for extraction quality. |
| **httpx** | HTTP client | Async, used for Ollama API calls and webhook delivery. Already a dependency. |
| **python-jose** | JWT auth | Industry-standard JWT implementation. Already a dependency. |
| **Pillow + PyMuPDF** | Document processing | Pillow for image preprocessing, PyMuPDF (fitz) for PDF text extraction and page-to-image conversion for OCR fallback. |
| **rapidfuzz** | Fuzzy matching | Fast Levenshtein distance for vendor name matching and duplicate detection. C-accelerated, no heavy dependencies. |
| **watchfiles** | Watch folder | Async-compatible filesystem watcher built on Rust notify. Efficient polling for new invoice files. |
| **Pydantic** | Schema validation | Request/response validation, settings management. Deep FastAPI integration. |
| **Alembic** | Migrations | Database schema versioning. Already configured. |
| **Ruff** | Linting/formatting | Fast Python linter. Already configured. |

---

## Milestones

### Milestone 1 — Core Extraction Engine (Priority: HIGHEST)

**Goal**: Upload a PDF/image invoice and get structured data back via LLM.

- [ ] Add `Invoice` and `LineItem` SQLAlchemy models with all fields
- [ ] Add `PurchaseOrder` model
- [ ] Create Alembic migration for new models
- [ ] Implement file upload endpoint (`POST /api/v1/invoices/upload`)
  - Accept PDF and image files (PNG, JPG, TIFF)
  - Compute SHA-256 hash, store file on disk
  - Create invoice record with `pending_extraction` status
- [ ] Build LLM extraction module (`src/invoiceflow/engine/extractor.py`)
  - Construct structured prompt for invoice data extraction
  - Call Ollama API (`/api/generate`) with invoice content
  - Parse LLM JSON response into Invoice + LineItem records
  - Assign confidence score based on response completeness
- [ ] PDF text extraction with PyMuPDF (text-based PDFs)
- [ ] Image-to-text via Ollama vision model (for scanned/image invoices)
- [ ] Invoice detail endpoint (`GET /api/v1/invoices/{id}`)
- [ ] Invoice list endpoint (`GET /api/v1/invoices`) with status/vendor/date filters
- [ ] Tests: upload → extract → verify structured output

**Deliverable**: Upload an invoice, get structured vendor/amount/line-item data.

### Milestone 2 — Validation & Duplicate Detection

**Goal**: Validate extracted invoices against POs and catch duplicates.

- [ ] Duplicate detection module (`src/invoiceflow/engine/duplicates.py`)
  - SHA-256 exact match (same file uploaded twice)
  - Fuzzy match: vendor name (rapidfuzz ratio > 85) + amount (within 1%) + date (within 3 days)
  - Return match confidence and matched invoice IDs
- [ ] PO validation module (`src/invoiceflow/engine/validator.py`)
  - Match invoice PO number to PurchaseOrder table
  - Compare vendor name (fuzzy), total amount (configurable tolerance)
  - Generate structured discrepancy flags (amount_mismatch, vendor_mismatch, po_not_found, etc.)
- [ ] PO CRUD endpoints (create, list, get)
- [ ] Expense categorization via LLM
- [ ] Flag invoices with discrepancies, update status
- [ ] Duplicate check endpoint (`GET /api/v1/invoices/{id}/duplicates`)
- [ ] Tests: duplicate detection accuracy, PO validation flag generation

**Deliverable**: Invoices validated against POs, duplicates caught, expenses categorized.

### Milestone 3 — Approval Workflow & Webhooks

**Goal**: Human-in-the-loop approval with real-time notifications.

- [ ] Approval endpoints (approve, reject with reason)
- [ ] Status transition enforcement (only `pending_approval` → approved/rejected)
- [ ] Webhook configuration model and CRUD
- [ ] Webhook delivery module with HMAC signing
  - Events: `invoice.extracted`, `invoice.flagged`, `invoice.approved`, `invoice.rejected`
  - Async delivery with retry (3 attempts, exponential backoff)
- [ ] Stats endpoint (`GET /api/v1/stats`) — totals, by status, by category, flagged count
- [ ] Tests: approval flow, webhook delivery, status transitions

**Deliverable**: Full approval pipeline with webhook notifications.

### Milestone 4 — Export & Watch Folder

**Goal**: Get data out in accounting formats, automate ingestion.

- [ ] CSV export module — single invoice and bulk export
- [ ] QuickBooks IIF export format
- [ ] Export endpoints (single and bulk)
- [ ] Watch folder background task (lifespan startup)
  - Monitor configured directory for new PDF/image files
  - Auto-ingest and trigger extraction pipeline
  - Move processed files to `processed/` subdirectory
- [ ] CLI commands (`invoiceflow-cli upload`, `invoiceflow-cli export`, `invoiceflow-cli status`)
- [ ] Tests: export format correctness, watch folder integration

**Deliverable**: Automated ingestion and accounting-ready exports.

### Milestone 5 — Hardening & Production Readiness

**Goal**: Security, performance, documentation, CI/CD.

- [ ] Role-based access control (admin, approver, viewer)
- [ ] Rate limiting on upload endpoint
- [ ] Input validation hardening (file size limits, type checking)
- [ ] Comprehensive test suite (unit, integration, e2e) — target 80%+ coverage
- [ ] Performance benchmarks (extraction latency, bulk export throughput)
- [ ] API documentation and usage examples
- [ ] Security audit (OWASP top 10 review)
- [ ] Container scanning and SBOM generation
- [ ] CI pipeline with lint, test, coverage gates

**Deliverable**: Production-ready deployment with full test coverage and documentation.
