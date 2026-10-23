"""Remember how far a CV batch has got so the recruiter is not left waiting blind."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import ScoringProgress
from app.schemas.screening import ScoringProgressRead

STALE_AFTER = timedelta(minutes=30)


def progress_label(phase: str, done: int, total: int, scored: int) -> str:
    """Short line shown beside the progress bar."""
    if phase == "scanning":
        return "Checking the mailbox…"
    if phase == "scoring":
        return f"Scored {done} of {total}"
    if phase == "complete" and total <= 0:
        return "No new CVs."
    if phase == "complete" and scored <= 0:
        return "Scoring finished. None of the CVs could be scored."
    if phase == "complete" and scored == 1:
        return "1 CV scored. Choose who to invite from the ranking."
    if phase == "complete":
        return f"{scored} CVs scored. Choose who to invite from the ranking."
    return ""


def present_progress(
    phase: str,
    total: int,
    done: int,
    scored: int,
    *,
    updated_at: datetime,
    now: datetime,
) -> ScoringProgressRead:
    """Hide a run that stopped updating, so the bar does not spin forever."""
    if phase in {"scanning", "scoring"} and now - updated_at > STALE_AFTER:
        phase = "idle"
    safe_done = max(done, 0)
    safe_total = max(total, 0)
    safe_scored = max(scored, 0)
    return ScoringProgressRead(
        phase=phase,
        total=safe_total,
        done=safe_done,
        scored=safe_scored,
        label=progress_label(phase, safe_done, safe_total, safe_scored),
    )


async def read_progress(session: AsyncSession, job_id: uuid.UUID, now: datetime | None = None) -> ScoringProgressRead:
    clock = now or datetime.now(UTC)
    row = await session.get(ScoringProgress, job_id)
    if row is None:
        return present_progress("idle", 0, 0, 0, updated_at=clock, now=clock)
    return present_progress(row.phase, row.total, row.done, row.scored, updated_at=row.updated_at, now=clock)


async def begin_scanning(session: AsyncSession, job_ids: list[uuid.UUID], now: datetime) -> None:
    """Show every open role as waiting on the mailbox, unless it is already scoring an upload."""
    for job_id in job_ids:
        row = await session.get(ScoringProgress, job_id)
        if row is not None and row.phase == "scoring":
            continue
        await _write(session, job_id, phase="scanning", total=0, done=0, scored=0, now=now)


async def begin_scoring(session: AsyncSession, job_id: uuid.UUID, total: int, now: datetime) -> ScoringProgressRead:
    row = await _write(session, job_id, phase="scoring", total=total, done=0, scored=0, now=now)
    return present_progress(row.phase, row.total, row.done, row.scored, updated_at=row.updated_at, now=now)


async def advance_progress(session: AsyncSession, job_id: uuid.UUID, *, scored: bool, now: datetime) -> None:
    row = await session.get(ScoringProgress, job_id)
    if row is None:
        return
    row.done += 1
    if scored:
        row.scored += 1
    if row.total > 0 and row.done >= row.total:
        row.phase = "complete"
    row.updated_at = now
    await session.flush()


async def stop_progress(session: AsyncSession, job_ids: list[uuid.UUID], now: datetime) -> None:
    """Close a run that failed, so the bar does not stay on screen."""
    for job_id in job_ids:
        row = await session.get(ScoringProgress, job_id)
        if row is None or row.phase not in {"scanning", "scoring"}:
            continue
        row.phase = "complete"
        row.updated_at = now
        await session.flush()


async def complete_if_scanning(session: AsyncSession, job_ids: list[uuid.UUID], now: datetime) -> None:
    for job_id in job_ids:
        row = await session.get(ScoringProgress, job_id)
        if row is None or row.phase != "scanning":
            continue
        row.phase = "complete"
        row.total = 0
        row.done = 0
        row.scored = 0
        row.updated_at = now


async def _write(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    phase: str,
    total: int,
    done: int,
    scored: int,
    now: datetime,
) -> ScoringProgress:
    row = await session.get(ScoringProgress, job_id)
    if row is None:
        row = ScoringProgress(job_id=job_id, phase=phase, total=total, done=done, scored=scored, updated_at=now)
        session.add(row)
        await session.flush()
        return row
    row.phase = phase
    row.total = total
    row.done = done
    row.scored = scored
    row.updated_at = now
    await session.flush()
    return row
