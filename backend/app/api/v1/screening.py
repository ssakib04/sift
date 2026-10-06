from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_embedder, get_llm
from app.core.config import Settings
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.schemas.screening import CandidateRead, InboxPollRead
from app.services.email_worker import ingest_inbox
from app.services.embeddings import Embedder
from app.services.invites import SmtpInviteSender
from app.services.mailpit import MailpitMailbox
from app.services.screening import list_ranked_candidates

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
        mailbox=MailpitMailbox(settings),
        sender=SmtpInviteSender(settings),
    )
    return InboxPollRead(processed=processed)


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateRead])
async def read_candidates(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[CandidateRead]:
    return await list_ranked_candidates(session, job_id)
