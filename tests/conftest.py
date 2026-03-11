"""Test fixtures."""

import pytest
from fastapi.testclient import TestClient

from invoiceflow.app import create_app


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app()
    with TestClient(app) as c:
        yield c
