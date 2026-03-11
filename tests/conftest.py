"""Test fixtures."""

import asyncio
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("INVOICEFLOW_DATA_DIR", tempfile.mkdtemp(prefix="invoiceflow_test_"))

from invoiceflow.app import create_app  # noqa: E402
from invoiceflow.database import Base, async_session, engine  # noqa: E402


async def _reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def client():
    """Create a test client with fresh DB (tables dropped and recreated)."""
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_reset_db())
    loop.close()

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def db_session():
    """Async DB session for direct engine tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        yield session


@pytest.fixture
def sample_invoice_data():
    """Sample invoice payload for testing."""
    return {
        "invoice_number": "INV-2026-001",
        "vendor_name": "Acme Office Supplies",
        "vendor_address": "123 Main St, Springfield, IL 62701",
        "invoice_date": "2026-03-01",
        "due_date": "2026-03-31",
        "subtotal": 450.00,
        "tax_amount": 36.00,
        "total_amount": 486.00,
        "currency": "USD",
        "po_number": "PO-1001",
        "line_items": [
            {
                "description": "Copy paper, 10 reams",
                "quantity": 10,
                "unit_price": 25.00,
                "amount": 250.00,
            },
            {
                "description": "Toner cartridge HP 26A",
                "quantity": 2,
                "unit_price": 100.00,
                "amount": 200.00,
            },
        ],
    }


@pytest.fixture
def sample_po_data():
    """Sample purchase order payload."""
    return {
        "po_number": "PO-1001",
        "vendor_name": "Acme Office Supplies",
        "total_amount": 486.00,
        "description": "Office supplies Q1 2026",
    }
