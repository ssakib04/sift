import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.llm_fallback import FallbackLLMManager
from app.services.embeddings import Embedder
from app.services.invites import InviteSender
from app.services.mailpit import Mailbox, MailAttachment
from app.services.ocr_service import InvalidCvError, validate_cv
from app.services.screening import JobMailKey, accept_cv, load_mail_keys, message_seen, record_intake

logger = logging.getLogger(__name__)


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
    if len(best) == 1:
        return best[0]
    return None


async def ingest_inbox(
    session: AsyncSession,
    settings: Settings,
    *,
    llm: FallbackLLMManager,
    embedder: Embedder,
    mailbox: Mailbox,
    sender: InviteSender,
) -> int:
    """Poll the inbox once. Matching CV mail is scored; everything else waits for a later poll."""
    keys = await load_mail_keys(session)
    summaries = await mailbox.list_summaries()
    processed = 0
    for summary in reversed(summaries):
        try:
            outcome = await _handle_summary(
                session,
                settings,
                llm=llm,
                embedder=embedder,
                mailbox=mailbox,
                sender=sender,
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
        if outcome == "scored":
            processed += 1
    return processed


async def _handle_summary(
    session: AsyncSession,
    settings: Settings,
    *,
    llm: FallbackLLMManager,
    embedder: Embedder,
    mailbox: Mailbox,
    sender: InviteSender,
    keys: Sequence[JobMailKey],
    message_id: str,
    subject: str,
    from_address: str,
) -> str:
    if await message_seen(session, message_id):
        return "seen"
    if from_address.casefold() == settings.invite_from_address.casefold():
        await record_intake(session, message_id, "ignored", None)
        return "ignored"
    matched = match_job(subject, keys)
    if matched is None:
        return "unmatched"
    message = await mailbox.read_message(message_id)
    attachment = _cv_attachment(message.attachments)
    if attachment is None:
        await record_intake(session, message_id, "ignored", matched.version_id)
        return "ignored"
    data = await mailbox.download(message_id, attachment.part_id)
    try:
        media_type = validate_cv(attachment.filename, data)
    except InvalidCvError:
        await record_intake(session, message_id, "ignored", matched.version_id)
        return "ignored"
    outcome = await accept_cv(
        session,
        settings,
        llm=llm,
        embedder=embedder,
        sender=sender,
        version_id=matched.version_id,
        message_id=message_id,
        from_address=message.from_address or from_address,
        filename=attachment.filename,
        data=data,
        media_type=media_type,
    )
    await record_intake(session, message_id, outcome, matched.version_id)
    return outcome


def _cv_attachment(attachments: Sequence[MailAttachment]) -> MailAttachment | None:
    for attachment in attachments:
        suffix = attachment.filename.lower()
        if suffix.endswith(".pdf") or suffix.endswith(".docx"):
            return attachment
    return None
