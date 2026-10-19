import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm_fallback import FallbackLLMManager
from app.schemas.screening import CvUploadItemRead, CvUploadRead
from app.services.embeddings import Embedder
from app.services.face_embed import create_face_embedder
from app.services.invites import InviteSender
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
    sender: InviteSender,
    job_id: uuid.UUID,
    files: list[UploadedCv],
) -> CvUploadRead:
    """Score uploaded CVs against one locked job and invite anyone new in the top 3."""
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
            continue
        try:
            outcome = await accept_cv(
                session,
                settings,
                llm=llm,
                embedder=embedder,
                sender=sender,
                face_embedder=face_embedder,
                version_id=matched.version_id,
                message_id=f"upload-{uuid.uuid4()}",
                from_address="",
                filename=filename,
                data=uploaded.data,
                media_type=media_type,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("cv_upload_failed filename=%s", filename)
            outcome = "failed"
        items.append(CvUploadItemRead(filename=filename, outcome=outcome))
    return _read(items)


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
