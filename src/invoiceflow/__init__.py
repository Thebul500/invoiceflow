"""invoiceflow — AI invoice processing pipeline. Ingests invoices (PDF, email, image) via watch folder or API, uses LLM (Ollama) to extract vendor, line items, amounts, dates, PO numbers. Validates against purchase orders, flags discrepancies, categorizes expenses, exports to CSV/QuickBooks format. Duplicate detection via fuzzy matching. Approval workflow with webhook notifications. REST API + CLI. FastAPI + SQLite."""

__version__ = "0.1.0"
