"""Tests for the InvoiceFlow CLI."""

import tempfile
from unittest.mock import AsyncMock, patch

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
