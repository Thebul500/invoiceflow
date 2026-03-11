"""Tests for the email inbox data ingestion module.

Tests IMAP email fetching, HTTP URL fetching (httpx.get), and the
full email ingestion pipeline against mocked IMAP servers.
"""

import imaplib
import tempfile
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from invoiceflow.engine.email_ingestor import (
    INVOICE_SUBJECT_KEYWORDS,
    connect_imap,
    fetch_and_save_invoice,
    fetch_invoice_url,
    ingest_from_mailbox,
    search_invoice_emails,
)


# --- fetch_invoice_url (httpx.get sync) ---


def test_fetch_invoice_url_success():
    """Sync HTTP fetch downloads file using httpx.get."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_resp = MagicMock()
        mock_resp.content = b"Invoice PDF content"
        mock_resp.raise_for_status = MagicMock()

        with patch("invoiceflow.engine.email_ingestor.httpx.get", return_value=mock_resp):
            path = fetch_invoice_url("https://example.com/invoice.pdf", dest_dir=tmpdir)

        assert path is not None
        assert Path(path).exists()
        assert Path(path).read_bytes() == b"Invoice PDF content"


def test_fetch_invoice_url_unsupported_type():
    """Sync HTTP fetch rejects unsupported file types."""
    result = fetch_invoice_url("https://example.com/file.docx")
    assert result is None


def test_fetch_invoice_url_http_error():
    """Sync HTTP fetch handles errors gracefully."""
    import httpx as httpx_mod

    with patch(
        "invoiceflow.engine.email_ingestor.httpx.get",
        side_effect=httpx_mod.HTTPError("Connection failed"),
    ):
        result = fetch_invoice_url("https://example.com/invoice.pdf")

    assert result is None


def test_fetch_invoice_url_auto_extension():
    """URL with no extension defaults to .pdf."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_resp = MagicMock()
        mock_resp.content = b"content"
        mock_resp.raise_for_status = MagicMock()

        with patch("invoiceflow.engine.email_ingestor.httpx.get", return_value=mock_resp):
            path = fetch_invoice_url("https://example.com/download", dest_dir=tmpdir)

        assert path is not None
        assert path.endswith(".pdf")


def test_fetch_and_save_invoice():
    """fetch_and_save_invoice is a convenience wrapper for fetch_invoice_url."""
    with patch(
        "invoiceflow.engine.email_ingestor.fetch_invoice_url",
        return_value="/tmp/test.pdf",
    ):
        result = fetch_and_save_invoice("https://example.com/invoice.pdf")
    assert result == "/tmp/test.pdf"


# --- connect_imap ---


def test_connect_imap_ssl():
    """IMAP connection with SSL."""
    mock_conn = MagicMock()
    mock_conn.login = MagicMock(return_value=("OK", [b"Logged in"]))

    with patch("invoiceflow.engine.email_ingestor.imaplib.IMAP4_SSL", return_value=mock_conn):
        conn = connect_imap(
            host="mail.example.com",
            port=993,
            user="test@example.com",
            password="secret",
            use_ssl=True,
        )

    assert conn is mock_conn
    mock_conn.login.assert_called_once_with("test@example.com", "secret")


def test_connect_imap_no_ssl():
    """IMAP connection without SSL."""
    mock_conn = MagicMock()
    mock_conn.login = MagicMock(return_value=("OK", [b"Logged in"]))

    with patch("invoiceflow.engine.email_ingestor.imaplib.IMAP4", return_value=mock_conn):
        conn = connect_imap(
            host="mail.example.com",
            port=143,
            user="test@example.com",
            password="secret",
            use_ssl=False,
        )

    assert conn is mock_conn


def test_connect_imap_no_credentials():
    """IMAP connection fails without credentials."""
    with pytest.raises(ValueError, match="IMAP user and password"):
        connect_imap(host="localhost", user="", password="")


# --- search_invoice_emails ---


def _make_invoice_email(subject: str, attachment_name: str | None = None) -> bytes:
    """Create a test email with optional PDF attachment."""
    msg = MIMEMultipart()
    msg["From"] = "vendor@example.com"
    msg["To"] = "ap@company.com"
    msg["Subject"] = subject
    msg.attach(MIMEText("Please find the invoice attached.", "plain"))

    if attachment_name:
        pdf_data = b"%PDF-1.4 test invoice content"
        att = MIMEApplication(pdf_data, _subtype="pdf")
        att.add_header("Content-Disposition", "attachment", filename=attachment_name)
        msg.attach(att)

    return msg.as_bytes()


def test_search_invoice_emails_finds_invoices():
    """Search finds emails with invoice-related subjects."""
    mock_conn = MagicMock()
    mock_conn.select = MagicMock(return_value=("OK", [b"5"]))
    mock_conn.search = MagicMock(return_value=("OK", [b"1 2"]))

    email1 = _make_invoice_email("Invoice #INV-001 from Acme", "invoice.pdf")
    email2 = _make_invoice_email("Your payment receipt", "receipt.pdf")

    mock_conn.fetch = MagicMock(
        side_effect=[
            ("OK", [(b"1", email1)]),
            ("OK", [(b"2", email2)]),
        ]
    )
    mock_conn.store = MagicMock(return_value=("OK", [b"Flags set"]))

    attachments = search_invoice_emails(mock_conn, folder="INBOX")
    # Should find attachments from both invoice-related emails
    assert len(attachments) >= 2


def test_search_invoice_emails_no_unread():
    """Search returns empty when no unread emails."""
    mock_conn = MagicMock()
    mock_conn.select = MagicMock(return_value=("OK", [b"0"]))
    mock_conn.search = MagicMock(return_value=("OK", [b""]))

    result = search_invoice_emails(mock_conn)
    assert result == []


def test_search_invoice_emails_skips_non_invoice():
    """Search skips emails without invoice-related subjects."""
    mock_conn = MagicMock()
    mock_conn.select = MagicMock(return_value=("OK", [b"1"]))
    mock_conn.search = MagicMock(return_value=("OK", [b"1"]))

    non_invoice_email = _make_invoice_email("Weekly newsletter update", "news.pdf")
    mock_conn.fetch = MagicMock(return_value=("OK", [(b"1", non_invoice_email)]))
    mock_conn.store = MagicMock()

    attachments = search_invoice_emails(mock_conn)
    # Should not find PDF attachments from non-invoice email
    pdf_attachments = [a for a in attachments if a[0].endswith(".pdf") and a[0] != "email_1.eml"]
    assert len(pdf_attachments) == 0


# --- invoice subject keywords ---


def test_invoice_subject_keywords():
    """Subject keywords cover common invoice-related terms."""
    assert "invoice" in INVOICE_SUBJECT_KEYWORDS
    assert "receipt" in INVOICE_SUBJECT_KEYWORDS
    assert "payment" in INVOICE_SUBJECT_KEYWORDS
    assert "bill" in INVOICE_SUBJECT_KEYWORDS


# --- ingest_from_mailbox ---


@pytest.mark.asyncio
async def test_ingest_from_mailbox_no_credentials():
    """Mailbox ingestion fails gracefully without credentials."""
    results = await ingest_from_mailbox(host="localhost", user="", password="")
    assert results == []


@pytest.mark.asyncio
async def test_ingest_from_mailbox_connection_error():
    """Mailbox ingestion fails gracefully on connection error."""
    with patch(
        "invoiceflow.engine.email_ingestor.connect_imap",
        side_effect=imaplib.IMAP4.error("Connection refused"),
    ):
        results = await ingest_from_mailbox(
            host="nonexistent.example.com",
            user="test",
            password="pass",
        )
    assert results == []


@pytest.mark.asyncio
async def test_ingest_from_mailbox_full_pipeline():
    """Full mailbox ingestion pipeline with mocked IMAP and ingest_file."""
    invoice_email = _make_invoice_email("Invoice #TEST-001", "invoice.pdf")

    mock_conn = MagicMock()
    mock_conn.select = MagicMock(return_value=("OK", [b"1"]))
    mock_conn.search = MagicMock(return_value=("OK", [b"1"]))
    mock_conn.fetch = MagicMock(return_value=("OK", [(b"1", invoice_email)]))
    mock_conn.store = MagicMock(return_value=("OK", [b"Flags set"]))
    mock_conn.logout = MagicMock()

    mock_ingest_result = {
        "id": 1,
        "invoice_number": "TEST-001",
        "vendor_name": "Acme",
        "total_amount": 500.0,
        "status": "pending",
        "category": "General Expense",
    }

    with (
        patch(
            "invoiceflow.engine.email_ingestor.connect_imap",
            return_value=mock_conn,
        ),
        patch(
            "invoiceflow.engine.email_ingestor.ingest_file",
            new_callable=AsyncMock,
            return_value=mock_ingest_result,
        ),
    ):
        results = await ingest_from_mailbox(
            host="mail.example.com",
            user="test@example.com",
            password="secret",
        )

    assert len(results) >= 1
    assert results[0]["invoice_number"] == "TEST-001"


# --- API route test ---


def test_email_ingest_endpoint_no_credentials(client):
    """Email ingest API endpoint handles missing credentials."""
    resp = client.post("/api/invoices/email-ingest", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_processed"] == 0
    assert data["successful"] == 0
