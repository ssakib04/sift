from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_embedder, get_llm
from app.core.config import Settings
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.models.candidate import CandidateFace
from app.schemas.screening import CandidateGroupRead, CandidateRead, InboxPollRead
from app.services.face_images import candidate_photo_file
from app.services.email_worker import ingest_inbox
from app.services.embeddings import Embedder
from app.services.gmail_mailbox import mailbox_from_settings
from app.services.invites import SmtpInviteSender
from app.services.screening import get_candidate, list_candidate_groups, list_ranked_candidates

router = APIRouter()


@router.post("/screening/poll", response_model=InboxPollRead)
async def poll_inbox(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    llm: FallbackLLMManager = Depends(get_llm),
    embedder: Embedder = Depends(get_embedder),
) -> InboxPollRead:
    processed = await ingest_inbox(
        session,
        settings,
        llm=llm,
        embedder=embedder,
        mailbox=mailbox_from_settings(settings),
        sender=SmtpInviteSender(settings),
    )
    return InboxPollRead(processed=processed)


@router.get("/candidates", response_model=list[CandidateGroupRead])
async def read_candidate_groups(session: AsyncSession = Depends(get_session)) -> list[CandidateGroupRead]:
    return await list_candidate_groups(session)


@router.get("/candidates/{candidate_id}/photo")
async def read_candidate_photo(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    face = await session.get(CandidateFace, candidate_id)
    path = candidate_photo_file(settings.cv_storage_dir, candidate_id, face.storage_path) if face is not None else None
    if path is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "PHOTO_NOT_FOUND", "message": "No portrait is stored for this candidate."},
        )
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/candidates/{candidate_id}", response_model=CandidateRead)
async def read_candidate(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> CandidateRead:
    candidate = await get_candidate(session, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail={"error_code": "CANDIDATE_NOT_FOUND", "message": "Candidate not found."})
    return candidate


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateRead])
async def read_candidates(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[CandidateRead]:
    return await list_ranked_candidates(session, job_id)
