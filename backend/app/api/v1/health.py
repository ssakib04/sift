"""Liveness endpoint for the Sift API."""

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

SERVICE_STATUS: Literal["healthy"] = "healthy"
SERVICE_NAME: Literal["sift-api"] = "sift-api"
SERVICE_VERSION: str = "0.1.0"

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Liveness payload returned by the health endpoint."""

    status: Literal["healthy"] = Field(description="Current service liveness state.")
    service: Literal["sift-api"] = Field(description="Stable service identifier.")
    version: str = Field(description="Deployed API version.", min_length=1)


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Returns the current liveness status of the Sift API.",
)
async def get_health() -> HealthResponse:
    """Report that the API process is serving requests."""
    return HealthResponse(
        status=SERVICE_STATUS,
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )
