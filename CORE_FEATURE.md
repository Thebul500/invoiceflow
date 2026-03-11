# Core Feature — invoiceflow

## What This Tool Must DO

AI invoice processing pipeline. Ingests invoices (PDF, email, image) via watch folder or API, uses LLM (Ollama) to extract vendor, line items, amounts, dates, PO numbers. Validates against purchase orders, flags discrepancies, categorizes expenses, exports to CSV/QuickBooks format. Duplicate detection via fuzzy matching. Approval workflow with webhook notifications. REST API + CLI. FastAPI + SQLite.

## Priority

The scaffolding (FastAPI app, auth, health endpoints, models, database) is ALREADY DONE.
DO NOT spend time on more CRUD endpoints, auth improvements, or API scaffolding.

Your #1 job is to implement the CORE DOMAIN LOGIC that makes this tool different from
a generic REST API. The above description tells you what that is.

## Implementation Checklist

- [ ] Core engine module (the code that DOES the thing described above)
- [ ] Integration with real targets (localhost, Docker socket, real APIs — not mocks)
- [ ] The tool produces REAL output when you run it
- [ ] Tests that verify the core feature works against real targets

## What NOT to Build

- More CRUD endpoints (already scaffolded)
- Auth improvements (already has JWT)
- CI/CD configs (comes later)
- Documentation (comes later)
- Docker improvements (comes later)
