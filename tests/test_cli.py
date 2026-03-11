"""Tests for the InvoiceFlow CLI."""

import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from invoiceflow.cli import build_parser, main


def test_cli_help(capsys):
    """CLI --help shows usage info."""
    parser = build_parser()
    parser.print_help()
    output = capsys.readouterr().out
    assert "ingest" in output
    assert "fetch" in output
    assert "export" in output
    assert "watch" in output
    assert "serve" in output


def test_cli_no_args(capsys):
    """CLI with no args prints help and exits 0."""
    with patch("sys.argv", ["invoiceflow"]):
        result = main()
    assert result == 0


def test_cli_ingest_command():
    """CLI ingest command calls ingest_file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Invoice #CLI-001\nVendor: CLI Test Corp\nTotal: $100.00")
        f.flush()
        txt_path = f.name

    mock_result = {
        "id": 1,
        "invoice_number": "CLI-001",
        "vendor_name": "CLI Test Corp",
        "total_amount": 100.0,
        "category": "General Expense",
        "status": "pending",
    }

    with (
        patch("sys.argv", ["invoiceflow", "ingest", txt_path]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.ingestor.ingest_file",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        result = main()

    assert result == 0


def test_cli_ingest_failure():
    """CLI ingest command handles failure."""
    with (
        patch("sys.argv", ["invoiceflow", "ingest", "/nonexistent.txt"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.ingestor.ingest_file",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = main()

    assert result == 1


def test_cli_fetch_command():
    """CLI fetch command calls fetch_from_url."""
    mock_result = {
        "id": 2,
        "invoice_number": "FETCH-001",
        "vendor_name": "Remote Corp",
        "total_amount": 200.0,
        "category": "General Expense",
        "status": "pending",
    }

    with (
        patch("sys.argv", ["invoiceflow", "fetch", "https://example.com/invoice.pdf"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.ingestor.fetch_from_url",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        result = main()

    assert result == 0


def test_cli_fetch_failure():
    """CLI fetch command handles failure."""
    with (
        patch("sys.argv", ["invoiceflow", "fetch", "https://example.com/bad.pdf"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.ingestor.fetch_from_url",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = main()

    assert result == 1


def test_cli_export_command():
    """CLI export command calls export_csv."""
    with (
        patch("sys.argv", ["invoiceflow", "export", "--format", "csv"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.exporter.export_csv",
            new_callable=AsyncMock,
            return_value="/tmp/export.csv",
        ),
    ):
        result = main()

    assert result == 0


def test_cli_export_iif_command():
    """CLI export IIF format."""
    with (
        patch("sys.argv", ["invoiceflow", "export", "--format", "iif"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.exporter.export_iif",
            new_callable=AsyncMock,
            return_value="/tmp/export.iif",
        ),
    ):
        result = main()

    assert result == 0


def test_cli_list_with_invoices(capsys):
    """CLI list command shows invoices."""
    from invoiceflow.models import Invoice

    mock_invoices = [
        Invoice(
            id=1,
            invoice_number="INV-001",
            vendor_name="Acme Corp",
            total_amount=500.0,
            status="pending",
            category="Office Supplies",
        ),
        Invoice(
            id=2,
            invoice_number="INV-002",
            vendor_name="Globex Inc",
            total_amount=1200.0,
            status="approved",
            category="IT & Software",
        ),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_invoices

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("sys.argv", ["invoiceflow", "list"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch("invoiceflow.database.async_session", return_value=mock_session),
    ):
        result = main()

    assert result == 0
    output = capsys.readouterr().out
    assert "Acme Corp" in output
    assert "2 invoice(s) shown" in output


def test_cli_list_empty(capsys):
    """CLI list command with no invoices."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("sys.argv", ["invoiceflow", "list"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch("invoiceflow.database.async_session", return_value=mock_session),
    ):
        result = main()

    assert result == 0
    output = capsys.readouterr().out
    assert "No invoices found" in output


def test_cli_status(capsys):
    """CLI status command shows pipeline stats."""
    mock_status = {
        "total_invoices": 10,
        "by_status": {"pending": 3, "approved": 5, "rejected": 1, "exported": 1},
        "duplicates_detected": 2,
        "ollama_model": "qwen2.5:14b",
        "ollama_url": "http://localhost:11434",
        "watch_dir": "/tmp/watch",
        "supported_formats": [".pdf", ".txt"],
    }

    with (
        patch("sys.argv", ["invoiceflow", "status"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch("invoiceflow.database.async_session") as mock_session_factory,
        patch(
            "invoiceflow.engine.pipeline.get_pipeline_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ),
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = mock_session

        result = main()

    assert result == 0
    output = capsys.readouterr().out
    assert "Total invoices:    10" in output
    assert "Pending:           3" in output


def test_cli_approve(capsys):
    """CLI approve command changes invoice status."""
    from invoiceflow.models import Invoice

    mock_invoice = Invoice(id=1, status="pending")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_invoice

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("sys.argv", ["invoiceflow", "approve", "1"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch("invoiceflow.database.async_session", return_value=mock_session),
    ):
        result = main()

    assert result == 0
    output = capsys.readouterr().out
    assert "pending -> approved" in output


def test_cli_reject(capsys):
    """CLI reject command changes invoice status."""
    from invoiceflow.models import Invoice

    mock_invoice = Invoice(id=2, status="pending")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_invoice

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("sys.argv", ["invoiceflow", "reject", "2"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch("invoiceflow.database.async_session", return_value=mock_session),
    ):
        result = main()

    assert result == 0
    output = capsys.readouterr().out
    assert "pending -> rejected" in output


def test_cli_approve_not_found(capsys):
    """CLI approve fails for nonexistent invoice."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("sys.argv", ["invoiceflow", "approve", "999"]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch("invoiceflow.database.async_session", return_value=mock_session),
    ):
        result = main()

    assert result == 1


def test_cli_serve():
    """CLI serve command calls uvicorn."""
    with (
        patch("sys.argv", ["invoiceflow", "serve", "--host", "0.0.0.0", "--port", "9000"]),
        patch("uvicorn.run") as mock_uvicorn,
    ):
        result = main()

    assert result == 0
    mock_uvicorn.assert_called_once_with(
        "invoiceflow.app:app",
        host="0.0.0.0",
        port=9000,
        reload=False,
    )


def test_cli_email_ingest(capsys):
    """CLI email-ingest command processes mailbox."""
    mock_results = [
        {"id": 1, "vendor_name": "Email Vendor", "total_amount": 300.0, "file": "invoice.pdf"},
        {"file": "bad.pdf", "error": "Ingestion failed"},
    ]

    with (
        patch("sys.argv", [
            "invoiceflow", "email-ingest",
            "--host", "mail.example.com",
            "--user", "test@example.com",
            "--password", "secret",
        ]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.email_ingestor.ingest_from_mailbox",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        result = main()

    assert result == 0
    output = capsys.readouterr().out
    assert "1 succeeded" in output


def test_cli_email_ingest_empty(capsys):
    """CLI email-ingest command with no emails."""
    with (
        patch("sys.argv", [
            "invoiceflow", "email-ingest",
            "--host", "mail.example.com",
            "--user", "test@example.com",
            "--password", "secret",
        ]),
        patch("invoiceflow.database.init_db", new_callable=AsyncMock),
        patch(
            "invoiceflow.engine.email_ingestor.ingest_from_mailbox",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = main()

    assert result == 0
    output = capsys.readouterr().out
    assert "No invoice emails found" in output
