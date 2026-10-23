import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm_fallback import FallbackLLMManager
from app.services.embeddings import Embedder
from app.services.face_embed import create_face_embedder
from app.services.mailpit import Mailbox, MailAttachment
from app.services.notices import ranking_notice_message, record_ranking_notice
from app.services.ocr_service import InvalidCvError, validate_cv
from app.services.scoring_progress import advance_progress, begin_scanning, begin_scoring, complete_if_scanning, stop_progress
from app.services.screening import JobMailKey, accept_cv, load_mail_keys, message_seen, record_intake

logger = logging.getLogger(__name__)


@dataclass
class _JobTally:
    title: str
    scored: int = 0
    unreadable: int = 0


@dataclass(frozen=True)
class PendingCv:
    message_id: str
    from_address: str
    filename: str
    data: bytes
    media_type: str
    version_id: uuid.UUID
    job_id: uuid.UUID
    title: str


def match_job(subject: str, jobs: Sequence[JobMailKey]) -> JobMailKey | None:
    """Bind a message to a locked job when the subject contains its id or saved subject."""
    folded = subject.casefold()
    for job in jobs:
        if str(job.job_id).casefold() in folded:
            return job
    matches = [
        job
        for job in jobs
        if len(job.mail_subject.strip()) >= 2 and job.mail_subject.casefold() in folded
    ]
    if not matches:
        return None
    best_length = max(len(job.mail_subject) for job in matches)
    best = [job for job in matches if len(job.mail_subject) == best_length]
    return max(best, key=lambda job: (job.locked_at, str(job.job_id)))


async def ingest_inbox(
    session: AsyncSession,
    settings: Settings,
    *,
    llm: FallbackLLMManager,
    embedder: Embedder,
    mailbox: Mailbox,
    announce: bool = False,
) -> int:
    """Poll the inbox once. Matching CV mail is scored; invitations wait for the recruiter."""
    keys = await load_mail_keys(session)
    job_ids = [key.job_id for key in keys]
    started: list[uuid.UUID] = []
    now = datetime.now(UTC)
    if announce:
        await begin_scanning(session, job_ids, now)
        await session.commit()
        started = list(job_ids)
    face_embedder = create_face_embedder(settings)
    pending: list[PendingCv] = []
    try:
        summaries = await mailbox.list_summaries()
        for summary in reversed(summaries):
            try:
                item = await _take_cv(
                    session,
                    settings,
                    mailbox=mailbox,
                    keys=keys,
                    message_id=summary.message_id,
                    subject=summary.subject,
                    from_address=summary.from_address,
                )
            except Exception:
                await session.rollback()
                logger.exception("message_failed id=%s", summary.message_id)
                continue
            await session.commit()
            if item is not None:
                pending.append(item)
        counts: dict[uuid.UUID, int] = {}
        for item in pending:
            counts[item.job_id] = counts.get(item.job_id, 0) + 1
        clock = datetime.now(UTC)
        for job_id, total in counts.items():
            await begin_scoring(session, job_id, total, clock)
            if job_id not in started:
                started.append(job_id)
        if announce:
            await complete_if_scanning(session, [job_id for job_id in job_ids if job_id not in counts], clock)
        await session.commit()
        processed = 0
        tallies: dict[uuid.UUID, _JobTally] = {}
        for item in pending:
            tally = tallies.get(item.job_id)
            if tally is None:
                tally = _JobTally(title=item.title)
                tallies[item.job_id] = tally
            try:
                outcome = await accept_cv(
                    session,
                    settings,
                    llm=llm,
                    embedder=embedder,
                    face_embedder=face_embedder,
                    version_id=item.version_id,
                    message_id=item.message_id,
                    from_address=item.from_address,
                    filename=item.filename,
                    data=item.data,
                    media_type=item.media_type,
                )
                await record_intake(session, item.message_id, outcome, item.version_id)
            except Exception:
                await session.rollback()
                logger.exception("message_failed id=%s", item.message_id)
                outcome = "failed"
                await record_intake(session, item.message_id, outcome, item.version_id)
            await advance_progress(session, item.job_id, scored=outcome == "scored", now=datetime.now(UTC))
            await session.commit()
            if outcome == "scored":
                processed += 1
                tally.scored += 1
            elif outcome == "parse_failed":
                tally.unreadable += 1
        noted = False
        notice_at = datetime.now(UTC)
        for job_id, tally in tallies.items():
            if tally.scored < 1:
                continue
            await record_ranking_notice(
                session,
                job_id=job_id,
                summary=ranking_notice_message(
                    job_title=tally.title,
                    scored=tally.scored,
                    unreadable=tally.unreadable,
                ),
                now=notice_at,
            )
            noted = True
        if noted:
            await session.commit()
        return processed
    except Exception:
        await session.rollback()
        await stop_progress(session, started, datetime.now(UTC))
        await session.commit()
        raise


async def _take_cv(
    session: AsyncSession,
    settings: Settings,
    *,
    mailbox: Mailbox,
    keys: Sequence[JobMailKey],
    message_id: str,
    subject: str,
    from_address: str,
) -> PendingCv | None:
    if await message_seen(session, message_id):
        return None
    if from_address.casefold() == settings.invite_from_address.casefold():
        await record_intake(session, message_id, "ignored", None)
        return None
    matched = match_job(subject, keys)
    if matched is None:
        return None
    message = await mailbox.read_message(message_id)
    attachment = _cv_attachment(message.attachments)
    if attachment is None:
        await record_intake(session, message_id, "ignored", matched.version_id)
        return None
    data = await mailbox.download(message_id, attachment.part_id)
    try:
        media_type = validate_cv(attachment.filename, data)
    except InvalidCvError:
        await record_intake(session, message_id, "ignored", matched.version_id)
        return None
    return PendingCv(
        message_id=message_id,
        from_address=message.from_address or from_address,
        filename=attachment.filename,
        data=data,
        media_type=media_type,
        version_id=matched.version_id,
        job_id=matched.job_id,
        title=matched.title,
    )


def _cv_attachment(attachments: Sequence[MailAttachment]) -> MailAttachment | None:
    for attachment in attachments:
        suffix = attachment.filename.lower()
        if suffix.endswith(".pdf") or suffix.endswith(".docx"):
            return attachment
    return None
