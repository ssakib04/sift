from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.core.database import get_session
from app.schemas.job import PublicJobRead
from app.services.job_service import get_public_job, list_public_jobs

router = APIRouter(prefix="/careers")


@router.get("", response_model=list[PublicJobRead])
async def read_public_jobs(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> list[PublicJobRead]:
    return await list_public_jobs(session, settings)


@router.get("/{version_id}", response_model=PublicJobRead)
async def read_public_job(
    version_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> PublicJobRead:
    job = await get_public_job(session, version_id, settings)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "JOB_NOT_FOUND", "message": "This job is not published."},
        )
    return job
