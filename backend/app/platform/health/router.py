"""Health check and observability endpoints."""

from fastapi import APIRouter

from app.common.config import settings
from app.platform.health.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service Health Check")
async def health_check() -> HealthResponse:
    """Liveness probe for orchestrators and load balancers."""
    return HealthResponse(status="healthy", environment=settings.ENVIRONMENT)
