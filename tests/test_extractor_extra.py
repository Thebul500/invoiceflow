"""Tests for extractor — image extraction, email with attachments, and Ollama call."""

import tempfile
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from invoiceflow.engine.extractor import (
    extract_invoice_data,
    extract_with_ollama,
    parse_email,
)


@pytest.mark.asyncio
async def test_extract_with_ollama_text():
    """extract_with_ollama sends text to Ollama API and parses JSON response."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": '{"invoice_number": "OLL-001", "total_amount": 500.0}'
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("invoiceflow.engine.extractor.httpx.AsyncClient", return_value=mock_client):
        result = await extract_with_ollama("Invoice #OLL-001\nTotal: $500.00")

    assert result["invoice_number"] == "OLL-001"
    assert result["total_amount"] == 500.0


@pytest.mark.asyncio
async def test_extract_with_ollama_with_image():
    """extract_with_ollama includes image in payload when provided."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": '{"invoice_number": "IMG-001", "total_amount": 300.0}'
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("invoiceflow.engine.extractor.httpx.AsyncClient", return_value=mock_client):
        result = await extract_with_ollama("scanned invoice", image_b64="base64data==")

    assert result["invoice_number"] == "IMG-001"
    # Verify image was included in the request
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert "images" in payload


@pytest.mark.asyncio
async def test_extract_invoice_data_image_file():
    """extract_invoice_data handles image files (PNG, JPG)."""
    # Create a fake image file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # Fake PNG header
        f.flush()
        img_path = f.name

    mock_ollama_result = {
        "invoice_number": "IMG-002",
        "vendor_name": "Image Vendor",
        "total_amount": 750.0,
    }

    with patch(
        "invoiceflow.engine.extractor.extract_with_ollama",
        new_callable=AsyncMock,
        return_value=mock_ollama_result,
    ):
        result = await extract_invoice_data(img_path)

    assert result["invoice_number"] == "IMG-002"
    assert result["file_hash"]
    assert result["raw_text"] == ""  # Images have no text


@pytest.mark.asyncio
async def test_extract_invoice_data_eml_with_pdf_attachment():
    """extract_invoice_data handles .eml files with PDF attachments."""
    # Create an email with a PDF attachment
    msg = MIMEMultipart()
    msg["From"] = "billing@vendor.com"
    msg["To"] = "ap@company.com"
    msg["Subject"] = "Invoice #EML-001"
    msg.attach(MIMEText("Please find invoice attached.", "plain"))

    # Create a minimal valid PDF
    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    pdf_att = MIMEApplication(pdf_content, _subtype="pdf")
    pdf_att.add_header("Content-Disposition", "attachment", filename="invoice.pdf")
    msg.attach(pdf_att)

    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False, mode="wb") as f:
        f.write(msg.as_bytes())
        eml_path = f.name

    mock_ollama_result = {
        "invoice_number": "EML-001",
        "vendor_name": "Email Vendor",
        "total_amount": 1000.0,
    }

    with (
        patch(
            "invoiceflow.engine.extractor.extract_with_ollama",
            new_callable=AsyncMock,
            return_value=mock_ollama_result,
        ),
        patch(
            "invoiceflow.engine.extractor.extract_text_from_pdf",
            return_value="PDF Invoice Text",
        ),
    ):
        result = await extract_invoice_data(eml_path)

    assert result["invoice_number"] == "EML-001"
    assert result["file_hash"]
    assert "raw_text" in result


@pytest.mark.asyncio
async def test_extract_invoice_data_eml_with_image_attachment():
    """extract_invoice_data handles .eml files with image attachments."""
    msg = MIMEMultipart()
    msg["From"] = "billing@vendor.com"
    msg["To"] = "ap@company.com"
    msg["Subject"] = "Invoice scan"
    msg.attach(MIMEText("Invoice scan attached.", "plain"))

    # Add an image attachment
    img_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    img_att = MIMEImage(img_data, _subtype="png")
    img_att.add_header("Content-Disposition", "attachment", filename="scan.png")
    msg.attach(img_att)

    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False, mode="wb") as f:
        f.write(msg.as_bytes())
        eml_path = f.name

    mock_ollama_result = {
        "invoice_number": "SCAN-001",
        "vendor_name": "Scan Vendor",
        "total_amount": 250.0,
    }

    with patch(
        "invoiceflow.engine.extractor.extract_with_ollama",
        new_callable=AsyncMock,
        return_value=mock_ollama_result,
    ):
        result = await extract_invoice_data(eml_path)

    assert result["invoice_number"] == "SCAN-001"
    assert result["file_hash"]


def test_parse_email_with_attachments():
    """parse_email extracts body text and attachment data."""
    msg = MIMEMultipart()
    msg["From"] = "vendor@example.com"
    msg["To"] = "ap@company.com"
    msg["Subject"] = "Invoice #PARSE-001"
    msg["Date"] = "Mon, 10 Mar 2026 10:00:00 -0600"
    msg.attach(MIMEText("Please pay this invoice.", "plain"))

    pdf_data = b"%PDF-1.4 fake content"
    att = MIMEApplication(pdf_data, _subtype="pdf")
    att.add_header("Content-Disposition", "attachment", filename="invoice.pdf")
    msg.attach(att)

    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False, mode="wb") as f:
        f.write(msg.as_bytes())
        eml_path = f.name

    body_text, attachments = parse_email(eml_path)

    assert "Invoice #PARSE-001" in body_text
    assert "vendor@example.com" in body_text
    assert len(attachments) == 1
    assert attachments[0][0] == "invoice.pdf"
    assert attachments[0][1] == pdf_data


def test_parse_email_no_attachments():
    """parse_email handles emails with no attachments."""
    msg = MIMEMultipart()
    msg["From"] = "sender@example.com"
    msg["Subject"] = "Plain email"
    msg.attach(MIMEText("Just a plain email body.", "plain"))

    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False, mode="wb") as f:
        f.write(msg.as_bytes())
        eml_path = f.name

    body_text, attachments = parse_email(eml_path)

    assert "Just a plain email body" in body_text
    assert attachments == []
