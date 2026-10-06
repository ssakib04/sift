from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_embedder, get_llm, get_poster
from app.core.config import Settings
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.job_creation_graph import JobGraphError
from app.schemas.job import JobCreateRequest, JobRead, JobVersionUpdate
from app.services.embeddings import Embedder
from app.services.job_rules import ChecklistLockedError
from app.services.job_service import approve_version, create_job, get_job, list_jobs, open_next_version, update_draft
from app.services.policy_ingest import PgPolicyRetriever
from app.services.postajob import JobPoster

router = APIRouter(prefix="/jobs")


@router.get("", response_model=list[JobRead])
async def read_jobs(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> list[JobRead]:
    return await list_jobs(session, settings)


@router.post("", response_model=JobRead, status_code=201)
async def create_job_route(
    request: JobCreateRequest,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_app_settings),
) -> JobRead:
    try:
        return await create_job(
            session,
            request,
            llm=llm,
            retriever=PgPolicyRetriever(session, embedder),
            settings=settings,
        )
    except JobGraphError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "JOB_GENERATION_INVALID", "message": str(exc)},
        ) from exc
    except LLMFallbackExhaustedError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "LLM_UNAVAILABLE", "message": "Every LLM tier failed."},
        ) from exc


@router.get("/{job_id}", response_model=JobRead)
async def read_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> JobRead:
    try:
        return await get_job(session, job_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "JOB_NOT_FOUND", "message": "Job not found."}) from exc


@router.patch("/{job_id}/versions/{version_number}", response_model=JobRead)
async def patch_version(
    job_id: UUID,
    version_number: int,
    update: JobVersionUpdate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> JobRead:
    try:
        return await update_draft(session, job_id, version_number, update, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "JOB_NOT_FOUND", "message": "Job not found."}) from exc
    except ChecklistLockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "CHECKLIST_LOCKED", "message": str(exc)},
        ) from exc


@router.post("/{job_id}/versions/{version_number}/approve", response_model=JobRead)
async def approve_job_version(
    job_id: UUID,
    version_number: int,
    session: AsyncSession = Depends(get_session),
    poster: JobPoster = Depends(get_poster),
    settings: Settings = Depends(get_app_settings),
) -> JobRead:
    try:
        return await approve_version(session, job_id, version_number, poster=poster, settings=settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "JOB_NOT_FOUND", "message": "Job not found."}) from exc
    except ChecklistLockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "CHECKLIST_LOCKED", "message": str(exc)},
        ) from exc


@router.post("/{job_id}/versions", response_model=JobRead, status_code=201)
async def create_next_version(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> JobRead:
    try:
        return await open_next_version(session, job_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "JOB_NOT_FOUND", "message": "Job not found."}) from exc
    except ChecklistLockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "CHECKLIST_LOCKED", "message": str(exc)},
        ) from exc
