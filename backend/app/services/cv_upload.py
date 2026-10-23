import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm_fallback import FallbackLLMManager
from app.schemas.screening import CvUploadItemRead, CvUploadRead
from app.services.embeddings import Embedder
from app.services.face_embed import create_face_embedder
from app.services.notices import ranking_notice_message, record_ranking_notice
from app.services.ocr_service import InvalidCvError, validate_cv
from app.services.screening import accept_cv, load_mail_keys

logger = logging.getLogger(__name__)

UPLOAD_LIMIT = 20


class UploadError(Exception):
    """A CV batch cannot be accepted for this job."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class UploadedCv:
    filename: str
    data: bytes


def check_upload_count(count: int) -> None:
    if count < 1:
        raise UploadError("CV_UPLOAD_EMPTY", "Choose at least one CV.")
    if count > UPLOAD_LIMIT:
        raise UploadError("CV_UPLOAD_LIMIT", "Upload at most 20 CVs at a time.")


async def upload_job_cvs(
    session: AsyncSession,
    settings: Settings,
    *,
    llm: FallbackLLMManager,
    embedder: Embedder,
    job_id: uuid.UUID,
    files: list[UploadedCv],
    on_settled: Callable[[str], Awaitable[None]] | None = None,
) -> CvUploadRead:
    """Score uploaded CVs against one locked job. The recruiter chooses who to invite."""
    check_upload_count(len(files))
    matched = next((key for key in await load_mail_keys(session) if key.job_id == job_id), None)
    if matched is None:
        raise UploadError("JOB_NOT_LOCKED", "Only a locked job can receive CVs.")
    face_embedder = create_face_embedder(settings)
    items: list[CvUploadItemRead] = []
    for uploaded in files:
        filename = Path(uploaded.filename).name or "cv"
        try:
            media_type = validate_cv(filename, uploaded.data)
        except InvalidCvError:
            items.append(CvUploadItemRead(filename=filename, outcome="invalid"))
            if on_settled is not None:
                await on_settled("invalid")
                await session.commit()
            continue
        try:
            outcome = await accept_cv(
                session,
                settings,
                llm=llm,
                embedder=embedder,
                face_embedder=face_embedder,
                version_id=matched.version_id,
                message_id=f"upload-{uuid.uuid4()}",
                from_address="",
                filename=filename,
                data=uploaded.data,
                media_type=media_type,
            )
            if on_settled is not None:
                await on_settled(outcome)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("cv_upload_failed filename=%s", filename)
            outcome = "failed"
            if on_settled is not None:
                await on_settled(outcome)
                await session.commit()
        items.append(CvUploadItemRead(filename=filename, outcome=outcome))
    result = _read(items)
    if result.scored > 0:
        await record_ranking_notice(
            session,
            job_id=matched.job_id,
            summary=ranking_notice_message(
                job_title=matched.title,
                scored=result.scored,
                unreadable=result.parse_failed,
            ),
            now=datetime.now(UTC),
        )
        await session.commit()
    return result


def _read(items: list[CvUploadItemRead]) -> CvUploadRead:
    def count(outcome: str) -> int:
        return sum(1 for item in items if item.outcome == outcome)

    return CvUploadRead(
        scored=count("scored"),
        duplicate=count("duplicate"),
        parse_failed=count("parse_failed"),
        invalid=count("invalid"),
        failed=count("failed"),
        items=items,
    )
