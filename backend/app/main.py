"""Sift Candidate Screening API application entrypoint."""

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.v1.health import SERVICE_VERSION

ALLOWED_ORIGINS: Sequence[str] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)

app = FastAPI(
    title="Sift Candidate Screening API",
    version=SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.include_router(api_router)
