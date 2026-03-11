"""Tests for core invoice processing features — extraction, validation, dedup, categorization, export.

Tests the domain-specific engine modules against real logic (not mocks).
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from invoiceflow.engine.categorizer import categorize_invoice
from invoiceflow.engine.duplicates import _compute_similarity, check_duplicates
from invoiceflow.engine.exporter import export_csv, export_iif
from invoiceflow.engine.extractor import (
    _is_image,
    _parse_llm_json,
    compute_file_hash,
    extract_text_from_pdf,
)
from invoiceflow.engine.ingestor import SUPPORTED_EXTENSIONS, InvoiceFileHandler, ingest_file
from invoiceflow.engine.validator import validate_against_po
from invoiceflow.models import Invoice, LineItem, PurchaseOrder


def test_parse_llm_json_clean():
    """Parse clean JSON from LLM response."""
    raw = '{"invoice_number": "INV-001", "total_amount": 100.0}'
    result = _parse_llm_json(raw)
    assert result["invoice_number"] == "INV-001"
    assert result["total_amount"] == 100.0


def test_parse_llm_json_with_markdown_fences():
    """Parse JSON wrapped in markdown code fences."""
    raw = '```json\n{"invoice_number": "INV-002", "vendor_name": "Acme"}\n```'
    result = _parse_llm_json(raw)
    assert result["invoice_number"] == "INV-002"
    assert result["vendor_name"] == "Acme"


def test_parse_llm_json_with_surrounding_text():
    """Parse JSON embedded in surrounding explanation text."""
    raw = 'Here is the extracted data:\n{"invoice_number": "INV-003"}\nDone.'
    result = _parse_llm_json(raw)
    assert result["invoice_number"] == "INV-003"


def test_parse_llm_json_invalid_returns_empty():
    """Invalid JSON returns empty dict."""
    result = _parse_llm_json("not json at all")
    assert result == {}


def test_compute_file_hash():
    """File hashing produces consistent SHA-256."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Invoice #12345\nTotal: $500.00")
        f.flush()
        hash1 = compute_file_hash(f.name)
        hash2 = compute_file_hash(f.name)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex length


def test_compute_file_hash_different_content():
    """Different files produce different hashes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f1:
        f1.write("file A")
        f1.flush()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f2:
        f2.write("file B")
        f2.flush()
    assert compute_file_hash(f1.name) != compute_file_hash(f2.name)


def test_categorize_office_supplies():
    """Invoices with office keywords get categorized correctly."""
    inv = Invoice(vendor_name="OfficeMax", line_items=[])
    inv.line_items.append(LineItem(description="Copy paper 10 reams", amount=50.0))
    inv.line_items.append(LineItem(description="Toner cartridge", amount=100.0))
    category = categorize_invoice(inv)
    assert category == "Office Supplies"


def test_categorize_it_software():
    """IT-related invoices categorized correctly."""
    inv = Invoice(vendor_name="CloudHost Inc", line_items=[])
    inv.line_items.append(LineItem(description="Cloud hosting monthly", amount=200.0))
    inv.line_items.append(LineItem(description="SSL certificate", amount=50.0))
    category = categorize_invoice(inv)
    assert category == "IT & Software"


def test_categorize_professional_services():
    """Legal/consulting invoices categorized correctly."""
    inv = Invoice(vendor_name="Smith & Associates", line_items=[])
    inv.line_items.append(LineItem(description="Legal consulting services", amount=5000.0))
    category = categorize_invoice(inv)
    assert category == "Professional Services"


def test_categorize_general_expense():
    """Unknown vendors get General Expense."""
    inv = Invoice(vendor_name="XYZ Corp", line_items=[])
    inv.line_items.append(LineItem(description="Widget type A", amount=100.0))
    category = categorize_invoice(inv)
    assert category == "General Expense"


def test_duplicate_similarity_exact_match():
    """Identical invoices have high similarity."""
    inv_a = Invoice(invoice_number="INV-001", vendor_name="Acme", total_amount=500.0)
    inv_b = Invoice(invoice_number="INV-001", vendor_name="Acme", total_amount=500.0)
    score = _compute_similarity(inv_a, inv_b)
    assert score >= 95.0


def test_duplicate_similarity_different():
    """Different invoices have low similarity."""
    inv_a = Invoice(invoice_number="INV-001", vendor_name="Acme", total_amount=500.0)
    inv_b = Invoice(invoice_number="INV-999", vendor_name="Globex", total_amount=12000.0)
    score = _compute_similarity(inv_a, inv_b)
    assert score < 50.0


def test_duplicate_similarity_partial():
    """Same vendor different invoice numbers — partial match."""
    inv_a = Invoice(invoice_number="INV-001", vendor_name="Acme Corp", total_amount=500.0)
    inv_b = Invoice(invoice_number="INV-002", vendor_name="Acme Corp", total_amount=500.0)
    score = _compute_similarity(inv_a, inv_b)
    assert 50.0 < score < 100.0  # high but not perfect


def test_extract_text_from_pdf():
    """PDF text extraction works on a real PDF file."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    from pypdf._page import PageObject

    page = PageObject.create_blank_page(width=612, height=792)
    writer.add_page(page)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        writer.write(f)
        pdf_path = f.name

    text = extract_text_from_pdf(pdf_path)
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_extract_invoice_data_calls_ollama():
    """extract_invoice_data calls Ollama with the text content."""
    from invoiceflow.engine.extractor import extract_invoice_data

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Invoice #TEST-001\nVendor: Test Corp\nTotal: $100.00")
        f.flush()
        txt_path = f.name

    mock_response = {
        "invoice_number": "TEST-001",
        "vendor_name": "Test Corp",
        "total_amount": 100.0,
        "line_items": [],
    }

    with patch(
        "invoiceflow.engine.extractor.extract_with_ollama",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await extract_invoice_data(txt_path)
    assert result["invoice_number"] == "TEST-001"
    assert "file_hash" in result
    assert "raw_text" in result


# --- Image detection ---


def test_is_image_true():
    """Image file extensions detected correctly."""
    assert _is_image("invoice.png") is True
    assert _is_image("scan.jpg") is True
    assert _is_image("PHOTO.JPEG") is True
    assert _is_image("doc.tiff") is True


def test_is_image_false():
    """Non-image files not detected as images."""
    assert _is_image("invoice.pdf") is False
    assert _is_image("invoice.txt") is False
    assert _is_image("data.csv") is False


# --- Duplicate similarity edge cases ---


def test_duplicate_similarity_no_invoice_numbers():
    """Both invoices missing invoice numbers — still compare vendor/amount."""
    inv_a = Invoice(vendor_name="Acme", total_amount=500.0)
    inv_b = Invoice(vendor_name="Acme", total_amount=500.0)
    score = _compute_similarity(inv_a, inv_b)
    assert score >= 55.0  # vendor (30%) + amount (30%) matched


def test_duplicate_similarity_one_missing_number():
    """One invoice has no number — score based on vendor/amount only."""
    inv_a = Invoice(invoice_number="INV-001", vendor_name="Acme", total_amount=500.0)
    inv_b = Invoice(vendor_name="Acme", total_amount=500.0)
    score = _compute_similarity(inv_a, inv_b)
    assert score < 65.0  # no number match contributes 0


def test_duplicate_similarity_zero_amount():
    """Invoice with zero amount doesn't cause division error."""
    inv_a = Invoice(invoice_number="INV-001", vendor_name="Acme", total_amount=0.0)
    inv_b = Invoice(invoice_number="INV-001", vendor_name="Acme", total_amount=100.0)
    score = _compute_similarity(inv_a, inv_b)
    assert score >= 0.0


# --- Categorizer edge cases ---


def test_categorize_no_vendor_no_items():
    """Invoice with no text data gets General Expense."""
    inv = Invoice(line_items=[])
    assert categorize_invoice(inv) == "General Expense"


def test_categorize_travel():
    """Travel keywords matched."""
    inv = Invoice(vendor_name="United Airlines", line_items=[])
    inv.line_items.append(LineItem(description="Flight to NYC", amount=400.0))
    assert categorize_invoice(inv) == "Travel & Entertainment"


def test_categorize_shipping():
    """Shipping keywords matched."""
    inv = Invoice(vendor_name="FedEx", line_items=[])
    inv.line_items.append(LineItem(description="Overnight shipping", amount=50.0))
    assert categorize_invoice(inv) == "Shipping & Logistics"


# --- Ingestor ---


def test_supported_extensions():
    """Ingestor supports expected file types."""
    assert ".pdf" in SUPPORTED_EXTENSIONS
    assert ".png" in SUPPORTED_EXTENSIONS
    assert ".jpg" in SUPPORTED_EXTENSIONS
    assert ".txt" in SUPPORTED_EXTENSIONS
    assert ".eml" in SUPPORTED_EXTENSIONS


def test_invoice_file_handler_ignores_directories():
    """InvoiceFileHandler ignores directory creation events."""
    from unittest.mock import MagicMock

    handler = InvoiceFileHandler()
    event = MagicMock()
    event.is_directory = True
    event.src_path = "/some/dir"
    handler.on_created(event)  # should not raise or queue


def test_invoice_file_handler_ignores_unsupported():
    """InvoiceFileHandler ignores unsupported file types."""
    from unittest.mock import MagicMock

    handler = InvoiceFileHandler()
    event = MagicMock()
    event.is_directory = False
    event.src_path = "/some/file.docx"
    handler.on_created(event)
    assert handler.queue.empty()


@pytest.mark.asyncio
async def test_ingest_nonexistent_file():
    """Ingesting a non-existent file returns None."""
    result = await ingest_file("/nonexistent/file.pdf")
    assert result is None


@pytest.mark.asyncio
async def test_ingest_unsupported_extension():
    """Ingesting an unsupported file type returns None."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(b"fake docx content")
        f.flush()

    result = await ingest_file(f.name)
    assert result is None
