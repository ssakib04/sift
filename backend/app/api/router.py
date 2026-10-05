"""Versioned API router for the Sift backend."""

from fastapi import APIRouter

from app.api.v1.cv import router as cv_router
from app.api.v1.health import router as health_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(cv_router, prefix="/cv", tags=["cv"])
