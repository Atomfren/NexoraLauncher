"""Health check."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    app_name: str


@router.get("/health", response_model=HealthResponse)
def health_check():
    """Проверка работоспособности backend."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        timestamp=datetime.now(UTC).isoformat(),
        app_name=settings.app_name,
    )


@router.get("/ping")
def ping():
    return {"pong": True}
