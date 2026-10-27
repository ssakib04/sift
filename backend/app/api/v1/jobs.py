import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_embedder, get_llm, get_poster
from app.core.config import Settings
from app.core.database import SessionFactory, get_session
from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.job_creation_graph import JobGraphError
from app.schemas.job import JobCreateRequest, JobRead, JobVersionUpdate
from app.schemas.final_ranking import ApprovalBatchRead, ApprovalRequest, FinalRankingRead
from app.schemas.screening import InviteBatchRead, InviteSelectionRequest, ScoringProgressRead
from app.services.cv_upload import UploadError, UploadedCv, check_upload_count, upload_job_cvs
from app.services.embeddings import Embedder
from app.services.final_ranking import FinalRankError, read_final_ranking, send_final_approvals
from app.services.invites import SmtpInviteSender
from app.services.job_rules import ChecklistLockedError
from app.services.job_service import approve_version, create_job, get_job, list_jobs, open_next_version, update_draft
from app.services.policy_ingest import PgPolicyRetriever
from app.services.postajob import JobPoster
from app.services.scoring_progress import advance_progress, begin_scoring, read_progress, stop_progress
from app.services.screening import InviteError, invite_selected, load_mail_keys

logger = logging.getLogger(__name__)

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


async def _score_upload(
    settings: Settings,
    llm: FallbackLLMManager,
    embedder: Embedder,
    job_id: UUID,
    files: list[UploadedCv],
) -> None:
    async with SessionFactory() as session:
        async def on_settled(outcome: str) -> None:
            await advance_progress(session, job_id, scored=outcome == "scored", now=datetime.now(UTC))

        try:
            await upload_job_cvs(
                session,
                settings,
                llm=llm,
                embedder=embedder,
                job_id=job_id,
                files=files,
                on_settled=on_settled,
            )
        except Exception:
            logger.exception("cv_upload_failed")
            await session.rollback()
            await stop_progress(session, [job_id], datetime.now(UTC))
            await session.commit()


@router.get("/{job_id}/scoring", response_model=ScoringProgressRead)
async def read_job_scoring(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ScoringProgressRead:
    return await read_progress(session, job_id)


@router.post("/{job_id}/cvs", response_model=ScoringProgressRead)
async def upload_cvs(
    job_id: UUID,
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_app_settings),
) -> ScoringProgressRead:
    payloads = [UploadedCv(filename=file.filename or "cv", data=await file.read()) for file in files]
    try:
        check_upload_count(len(payloads))
    except UploadError as exc:
        raise HTTPException(status_code=422, detail={"error_code": exc.code, "message": exc.message}) from exc
    matched = next((key for key in await load_mail_keys(session) if key.job_id == job_id), None)
    if matched is None:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "JOB_NOT_LOCKED", "message": "Only a locked job can receive CVs."},
        )
    progress = await begin_scoring(session, job_id, len(payloads), datetime.now(UTC))
    await session.commit()
    background.add_task(_score_upload, settings, llm, embedder, job_id, payloads)
    return progress


@router.post("/{job_id}/invitations", response_model=InviteBatchRead)
async def send_invitations(
    job_id: UUID,
    request: InviteSelectionRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InviteBatchRead:
    try:
        result = await invite_selected(
            session,
            settings,
            SmtpInviteSender(settings),
            job_id,
            request.candidate_ids,
        )
    except InviteError as exc:
        status = 409 if exc.code == "JOB_NOT_LOCKED" else 422
        raise HTTPException(status_code=status, detail={"error_code": exc.code, "message": exc.message}) from exc
    await session.commit()
    return result


@router.get("/{job_id}/final-ranking", response_model=FinalRankingRead)
async def read_job_final_ranking(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> FinalRankingRead:
    try:
        return await read_final_ranking(session, job_id)
    except FinalRankError as exc:
        raise _final_rank_http(exc) from exc


@router.post("/{job_id}/approvals", response_model=ApprovalBatchRead)
async def send_job_approvals(
    job_id: UUID,
    request: ApprovalRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> ApprovalBatchRead:
    try:
        result = await send_final_approvals(session, settings, SmtpInviteSender(settings), job_id, request.count)
    except FinalRankError as exc:
        raise _final_rank_http(exc) from exc
    await session.commit()
    return result


def _final_rank_http(exc: FinalRankError) -> HTTPException:
    status = 404 if exc.code == "JOB_NOT_FOUND" else 422
    return HTTPException(status_code=status, detail={"error_code": exc.code, "message": exc.message})


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
