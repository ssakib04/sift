from fastapi import APIRouter

from app.api.v1.careers import router as careers_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.policies import router as policies_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(policies_router, tags=["policies"])
api_router.include_router(jobs_router, tags=["jobs"])
api_router.include_router(careers_router, tags=["careers"])
api_router.include_router(copilot_router, tags=["copilot"])
