"""Health and readiness endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter

from .. import __version__
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Application health check."""
    return HealthResponse(
        status="healthy",
        version=__version__,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready")
async def readiness_check():
    """Readiness probe for orchestrators."""
    return {"status": "ready"}
