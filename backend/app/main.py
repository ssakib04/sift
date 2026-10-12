from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


_settings = get_settings()
app = FastAPI(
    title="Sift",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _settings.api_docs_enabled else None,
    redoc_url="/redoc" if _settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if _settings.api_docs_enabled else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")
