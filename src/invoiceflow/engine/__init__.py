"""InvoiceFlow processing engine — extraction, validation, dedup, categorization, export.

Data ingestion pipeline:
- File ingestion: PDF, image, email, text files via watch folder or API
- HTTP fetching: Download invoice files from remote URLs via httpx.get
- IMAP email ingestion: Fetch invoices from email inboxes via IMAP
- LLM extraction: Send text/images to Ollama for structured data extraction
- PO validation: Compare extracted data against purchase orders
- Duplicate detection: Fuzzy matching via rapidfuzz
- Expense categorization: Keyword-based category assignment
- Export: CSV and QuickBooks IIF format
"""

from .categorizer import categorize_invoice
from .duplicates import check_duplicates
from .email_ingestor import fetch_invoice_url, ingest_from_mailbox
from .exporter import export_csv, export_iif
from .extractor import extract_invoice_data, extract_text_from_pdf, extract_with_ollama
from .ingestor import fetch_from_url, ingest_file, start_watcher
from .pipeline import fetch_and_process, get_pipeline_status, process_directory, process_invoice
from .validator import validate_against_po

__all__ = [
    "categorize_invoice",
    "check_duplicates",
    "export_csv",
    "export_iif",
    "extract_invoice_data",
    "extract_text_from_pdf",
    "extract_with_ollama",
    "fetch_and_process",
    "fetch_from_url",
    "fetch_invoice_url",
    "get_pipeline_status",
    "ingest_file",
    "ingest_from_mailbox",
    "process_directory",
    "process_invoice",
    "start_watcher",
    "validate_against_po",
]
