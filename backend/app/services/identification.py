"""Store a CV face, then compare a consented camera frame with enrolled candidates."""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.session_tokens import SessionClaims
from app.models.candidate import (
    Candidate,
    CandidateFace,
    CandidateProfile,
    FaceCheck,
    InterviewSession,
    ScoreSnapshot,
)
from app.models.job import JobChecklistQuery, JobVersion
from app.services.face_embed import FaceEmbedder, FaceSample, create_face_embedder
from app.services.face_identity import (
    USABLE_TARGET,
    EnrolledFace,
    FaceStep,
    IdentityDecision,
    append_face_sample,
    conclude_face_samples,
    cosine,
    decode_frame,
    decide_identity,
    identification_message,
    probe_areas,
    profile_from_attributes,
    stored_samples,
)
from app.services.face_images import enroll_from_document, write_face_crop
from app.services.interview_rules import InterviewError, assert_candidate, assert_recruiter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileOverview:
    candidate_id: uuid.UUID
    full_name: str
    headline: str
    skills: list[str]
    pre_interview_score: float | None
    probe_areas: list[str]


@dataclass(frozen=True)
class IdentificationView:
    status: str
    message: str
    similarity: float | None
    invited_similarity: float | None
    invited_name: str
    matched_name: str | None
    hint_name: str | None
    profile: ProfileOverview | None
    concluded: bool = False
    sample_count: int = 0
    sample_limit: int = USABLE_TARGET


def store_candidate_profile(candidate_id: uuid.UUID, attributes: dict[str, object]) -> CandidateProfile:
    headline, skills, years = profile_from_attributes(attributes)
    return CandidateProfile(
        candidate_id=candidate_id,
        headline=headline,
        skills=skills,
        experience_years=years,
    )


def store_candidate_face(
    storage_dir: str,
    candidate_id: uuid.UUID,
    filename: str,
    data: bytes,
    embedder: FaceEmbedder,
    *,
    now: datetime | None = None,
) -> tuple[CandidateFace | None, str]:
    """Enroll a CV photo. A missing face is a warning, not a failed application."""
    try:
        sample = enroll_from_document(filename, data, embedder)
    except Exception as exc:
        logger.warning("face_enroll_failed error_type=%s", type(exc).__name__)
        return None, "No face photo could be enrolled from the CV."
    if sample is None:
        return None, "No face photo could be enrolled from the CV."
    path = write_face_crop(storage_dir, candidate_id, sample.portrait_jpeg or sample.crop_jpeg)
    face = CandidateFace(
        candidate_id=candidate_id,
        storage_path=path,
        embedding=sample.embedding,
        det_score=sample.confidence,
        enrolled_at=now or datetime.now(UTC),
    )
    return face, ""


async def identify_frame(
    db: AsyncSession,
    settings: Settings,
    claims: SessionClaims,
    image_base64: str,
) -> IdentificationView:
    assert_candidate(claims.role)
    row = await _session(db, claims)
    if row.biometric_consented_at is None:
        raise InterviewError(
            "BIOMETRIC_CONSENT_REQUIRED",
            "Face identification waits until the candidate agrees.",
            403,
        )
    if row.status != "started":
        raise InterviewError("SESSION_NOT_STARTED", "The interview has not started.", 409)
    existing = await db.get(FaceCheck, row.id)
    if existing is not None and _finished(existing):
        return await _view_from_check(db, row, existing)
    try:
        raw = decode_frame(image_base64)
    except ValueError as exc:
        code = "FRAME_TOO_LARGE" if "too large" in str(exc) else "FRAME_INVALID"
        raise InterviewError(code, str(exc), 400) from exc
    sample = await _embed(settings, raw)
    invited_embedding = await _invited_embedding(db, row.candidate_id)
    invited_similarity = None
    if sample is not None and invited_embedding is not None:
        invited_similarity = cosine(sample.embedding, invited_embedding)
    prior = list(existing.samples or []) if existing is not None else []
    samples = append_face_sample(
        prior,
        embedding=None if sample is None else sample.embedding,
        det_score=0.0 if sample is None else sample.confidence,
        invited_similarity=invited_similarity,
    )
    step = conclude_face_samples(
        samples,
        confirm=settings.face_confirm_threshold,
        possible=settings.face_possible_threshold,
    )
    if step is None:
        _store_check(db, existing, row.id, samples, IdentityDecision("checking", None, None, None), done=False)
        await db.commit()
        invited_name = _display_name(row.candidate.full_name if row.candidate is not None else "")
        usable = sum(1 for item in samples if item.get("kind") == "face")
        return _checking(invited_name, usable)
    decision = await _decision_from_step(db, settings, row.candidate_id, invited_embedding, step)
    _store_check(db, existing, row.id, stored_samples(samples), decision, done=True)
    await db.commit()
    usable = sum(1 for item in samples if item.get("kind") == "face")
    return await _view(db, row, decision, concluded=True, sample_count=usable)


async def read_identification(db: AsyncSession, claims: SessionClaims) -> IdentificationView:
    assert_recruiter(claims.role)
    row = await _session(db, claims)
    invited_name = _display_name(row.candidate.full_name if row.candidate is not None else "")
    if row.biometric_consented_at is None:
        return _plain("consent_required", invited_name)
    check = await db.get(FaceCheck, row.id)
    if check is None:
        return _plain("pending", invited_name)
    if not _finished(check):
        return _checking(invited_name, len(check.samples or []))
    return await _view_from_check(db, row, check)


async def _view_from_check(db: AsyncSession, row: InterviewSession, check: FaceCheck) -> IdentificationView:
    decision = IdentityDecision(
        status=check.status,
        matched_candidate_id=check.matched_candidate_id,
        similarity=check.similarity,
        invited_similarity=check.invited_similarity,
        ambiguous=check.ambiguous,
    )
    count = sum(1 for sample in (check.samples or []) if sample.get("kind") == "face") or USABLE_TARGET
    return await _view(db, row, decision, concluded=True, sample_count=count)


def _finished(check: FaceCheck) -> bool:
    if check.concluded:
        return True
    samples = check.samples or []
    return not samples and check.status in {"confirmed", "other_candidate", "low_confidence", "no_match", "no_face"}


def _store_check(
    db: AsyncSession,
    existing: FaceCheck | None,
    session_id: uuid.UUID,
    samples: list[dict[str, object]],
    decision: IdentityDecision,
    *,
    done: bool,
) -> None:
    status = decision.status if done else "checking"
    matched = decision.matched_candidate_id if done else None
    similarity = decision.similarity if done else None
    invited_similarity = decision.invited_similarity if done else None
    ambiguous = decision.ambiguous if done else False
    if existing is None:
        db.add(
            FaceCheck(
                session_id=session_id,
                status=status,
                matched_candidate_id=matched,
                similarity=similarity,
                invited_similarity=invited_similarity,
                ambiguous=ambiguous,
                samples=samples,
                concluded=done,
                checked_at=datetime.now(UTC),
            )
        )
        return
    existing.status = status
    existing.matched_candidate_id = matched
    existing.similarity = similarity
    existing.invited_similarity = invited_similarity
    existing.ambiguous = ambiguous
    existing.samples = samples
    existing.concluded = done
    existing.checked_at = datetime.now(UTC)


async def _embed(settings: Settings, raw: bytes) -> FaceSample | None:
    embedder = create_face_embedder(settings)
    try:
        return await asyncio.to_thread(embedder.embed, raw)
    except Exception as exc:
        logger.warning("face_match_failed error_type=%s", type(exc).__name__)
        return None


async def _invited_embedding(db: AsyncSession, candidate_id: uuid.UUID) -> list[float] | None:
    row = await db.get(CandidateFace, candidate_id)
    if row is None:
        return None
    return [float(value) for value in row.embedding]


async def _decision_from_step(
    db: AsyncSession,
    settings: Settings,
    invited_id: uuid.UUID,
    invited_embedding: list[float] | None,
    step: FaceStep,
) -> IdentityDecision:
    if step.action == "confirmed":
        return IdentityDecision("confirmed", invited_id, step.invited_similarity, step.invited_similarity)
    if step.action == "no_face":
        return IdentityDecision("no_face", None, None, None)
    if step.action == "search" and step.embedding is not None:
        return decide_identity(
            live=step.embedding,
            invited_id=invited_id,
            invited_embedding=invited_embedding,
            gallery=await _gallery(db),
            confirm=settings.face_confirm_threshold,
            possible=settings.face_possible_threshold,
        )
    return IdentityDecision("low_confidence", None, step.invited_similarity, step.invited_similarity)


async def _gallery(db: AsyncSession) -> list[EnrolledFace]:
    rows = list((await db.scalars(select(CandidateFace))).all())
    gallery: list[EnrolledFace] = []
    for row in rows:
        vector = [float(value) for value in row.embedding]
        gallery.append(EnrolledFace(candidate_id=row.candidate_id, embedding=vector))
    return gallery


async def _view(
    db: AsyncSession,
    row: InterviewSession,
    decision: IdentityDecision,
    *,
    concluded: bool = False,
    sample_count: int = 0,
) -> IdentificationView:
    invited_name = _display_name(row.candidate.full_name if row.candidate is not None else "")
    profile: ProfileOverview | None = None
    matched_name: str | None = None
    hint_name: str | None = None
    if decision.status in {"confirmed", "other_candidate"} and decision.matched_candidate_id is not None:
        profile = await _overview(db, decision.matched_candidate_id)
        if profile is not None:
            matched_name = profile.full_name
    elif decision.status == "low_confidence" and not decision.ambiguous and decision.matched_candidate_id is not None:
        hint = await db.get(Candidate, decision.matched_candidate_id)
        if hint is not None and hint.full_name.strip():
            hint_name = hint.full_name.strip()
    return IdentificationView(
        status=decision.status,
        message=identification_message(
            decision.status,
            invited_name=invited_name,
            matched_name=matched_name,
            hint_name=hint_name,
            ambiguous=decision.ambiguous,
        ),
        similarity=decision.similarity,
        invited_similarity=decision.invited_similarity,
        invited_name=invited_name,
        matched_name=matched_name,
        hint_name=hint_name,
        profile=profile if concluded else None,
        concluded=concluded,
        sample_count=sample_count,
    )


async def _overview(db: AsyncSession, candidate_id: uuid.UUID) -> ProfileOverview | None:
    candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .options(
            selectinload(Candidate.profile),
            selectinload(Candidate.snapshot).selectinload(ScoreSnapshot.evaluations),
        )
    )
    if candidate is None:
        return None
    queries = list(
        (
            await db.scalars(select(JobChecklistQuery).where(JobChecklistQuery.version_id == candidate.job_version_id))
        ).all()
    )
    queries.sort(key=lambda query: int(query.query_id[1:]) if query.query_id[1:].isdigit() else 0)
    status_by_query = {}
    score: float | None = None
    if candidate.snapshot is not None:
        score = candidate.snapshot.aggregate_score
        status_by_query = {item.query_id: item.status for item in candidate.snapshot.evaluations}
    pairs = [
        (status_by_query[query.query_id], query.question) for query in queries if query.query_id in status_by_query
    ]
    profile = candidate.profile
    return ProfileOverview(
        candidate_id=candidate.id,
        full_name=_display_name(candidate.full_name),
        headline=profile.headline if profile is not None else "",
        skills=list(profile.skills) if profile is not None else [],
        pre_interview_score=score,
        probe_areas=probe_areas(pairs),
    )


async def _session(db: AsyncSession, claims: SessionClaims) -> InterviewSession:
    row = await db.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == claims.session_id)
        .options(selectinload(InterviewSession.candidate).selectinload(Candidate.version).selectinload(JobVersion.job))
    )
    if row is None or row.candidate is None or row.candidate.version is None or row.candidate.version.job is None:
        raise InterviewError("SESSION_NOT_FOUND", "This interview session is not available.", 404)
    job = row.candidate.version.job
    if row.candidate_id != claims.candidate_id or job.id != claims.job_id:
        raise InterviewError("INTERVIEW_FORBIDDEN", "This link does not match the interview.", 403)
    return row


def _plain(status: str, invited_name: str) -> IdentificationView:
    return IdentificationView(
        status=status,
        message=identification_message(
            status,
            invited_name=invited_name,
            matched_name=None,
            hint_name=None,
            ambiguous=False,
        ),
        similarity=None,
        invited_similarity=None,
        invited_name=invited_name,
        matched_name=None,
        hint_name=None,
        profile=None,
    )


def _checking(invited_name: str, sample_count: int) -> IdentificationView:
    return IdentificationView(
        status="checking",
        message="Checking identity.",
        similarity=None,
        invited_similarity=None,
        invited_name=invited_name,
        matched_name=None,
        hint_name=None,
        profile=None,
        concluded=False,
        sample_count=sample_count,
    )


def _display_name(full_name: str) -> str:
    cleaned = full_name.strip()
    return cleaned or "Unnamed"
