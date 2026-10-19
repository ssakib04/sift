"""Decide whether a live face matches an enrolled candidate. Weak matches stay unnamed."""

import base64
import math
import uuid
from dataclasses import dataclass

from app.models.candidate import FACE_DIMENSIONS

CONFIRM_THRESHOLD = 0.42
POSSIBLE_THRESHOLD = 0.32
AMBIGUITY_GAP = 0.05
USABLE_TARGET = 3
USABLE_LIMIT = 6
EMPTY_LIMIT = 6
FACE_SAMPLE_LIMIT = USABLE_TARGET
_PROBE_STATUSES = {"unmet", "partially_met", "insufficient_evidence"}


@dataclass(frozen=True)
class EnrolledFace:
    candidate_id: uuid.UUID
    embedding: list[float]


@dataclass(frozen=True)
class IdentityDecision:
    status: str
    matched_candidate_id: uuid.UUID | None
    similarity: float | None
    invited_similarity: float | None
    ambiguous: bool = False


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two face embeddings."""
    if len(left) != FACE_DIMENSIONS or len(right) != FACE_DIMENSIONS:
        raise ValueError("Face embeddings must be 512 dimensions.")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def decide_identity(
    *,
    live: list[float] | None,
    invited_id: uuid.UUID,
    invited_embedding: list[float] | None,
    gallery: list[EnrolledFace],
    confirm: float = CONFIRM_THRESHOLD,
    possible: float = POSSIBLE_THRESHOLD,
) -> IdentityDecision:
    """Compare one live face with the invited candidate, then the rest of the gallery."""
    if not 0 <= possible < confirm <= 1:
        raise ValueError("Face thresholds are not ordered.")
    if live is None:
        return IdentityDecision("no_face", None, None, None)
    if len(live) != FACE_DIMENSIONS:
        raise ValueError("Face embeddings must be 512 dimensions.")

    scored: list[tuple[uuid.UUID, float]] = []
    invited_similarity: float | None = None
    seen_invited = False
    if invited_embedding is not None:
        invited_similarity = cosine(live, invited_embedding)
        scored.append((invited_id, invited_similarity))
        seen_invited = True
    for face in gallery:
        if len(face.embedding) != FACE_DIMENSIONS:
            continue
        if face.candidate_id == invited_id:
            if seen_invited:
                continue
            invited_similarity = cosine(live, face.embedding)
            scored.append((invited_id, invited_similarity))
            seen_invited = True
            continue
        scored.append((face.candidate_id, cosine(live, face.embedding)))
    if not scored:
        return IdentityDecision("no_match", None, None, invited_similarity)

    scored.sort(key=lambda item: item[1], reverse=True)
    best_id, best_similarity = scored[0]
    second_similarity = scored[1][1] if len(scored) > 1 else None
    if best_similarity < possible:
        return IdentityDecision("no_match", None, best_similarity, invited_similarity)
    if best_similarity < confirm:
        return IdentityDecision("low_confidence", best_id, best_similarity, invited_similarity)
    if (
        second_similarity is not None
        and second_similarity >= confirm
        and best_similarity - second_similarity < AMBIGUITY_GAP
    ):
        return IdentityDecision("low_confidence", None, best_similarity, invited_similarity, ambiguous=True)
    if best_id == invited_id:
        return IdentityDecision("confirmed", invited_id, best_similarity, invited_similarity)
    return IdentityDecision("other_candidate", best_id, best_similarity, invited_similarity)


def profile_from_attributes(attributes: dict[str, object]) -> tuple[str, list[str], float]:
    """Headline, skills, and years taken from the CV attributes screening already extracted."""
    headline = ""
    work = attributes.get("work_history")
    if isinstance(work, list):
        for item in work:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            company = str(item.get("company") or "").strip()
            headline = " · ".join(part for part in (title, company) if part)
            if headline:
                break
    skills: list[str] = []
    raw_skills = attributes.get("skills")
    if isinstance(raw_skills, list):
        for skill in raw_skills:
            if isinstance(skill, str) and skill.strip():
                skills.append(skill.strip())
            if len(skills) == 8:
                break
    years_raw = attributes.get("experience_years")
    years = float(years_raw) if isinstance(years_raw, int | float) and not isinstance(years_raw, bool) else 0.0
    if not headline and years > 0:
        shown = int(years) if years.is_integer() else round(years, 1)
        headline = f"{shown} years of experience"
    return headline, skills, years


def probe_areas(rows: list[tuple[str, str]], *, limit: int = 5) -> list[str]:
    """Checklist questions that were not fully met. These are the areas to probe."""
    areas = [question.strip() for status, question in rows if status in _PROBE_STATUSES and question.strip()]
    return areas[:limit]


@dataclass(frozen=True)
class FaceStep:
    """What to do with the usable frames gathered so far."""

    action: str
    invited_similarity: float | None = None
    embedding: list[float] | None = None


def append_face_sample(
    samples: list[dict[str, object]],
    *,
    embedding: list[float] | None,
    det_score: float = 0.0,
    invited_similarity: float | None = None,
) -> list[dict[str, object]]:
    """Keep usable faces. Frames with no face are counted separately and cannot vote."""
    if embedding is None:
        empty = sum(1 for sample in samples if sample.get("kind") == "empty")
        if empty >= EMPTY_LIMIT:
            return list(samples)
        return [*samples, {"kind": "empty"}]
    usable = sum(1 for sample in samples if sample.get("kind") == "face")
    if usable >= USABLE_LIMIT:
        return list(samples)
    return [
        *samples,
        {
            "kind": "face",
            "invited_similarity": invited_similarity,
            "det_score": det_score,
            "embedding": [float(value) for value in embedding],
        },
    ]


def conclude_face_samples(
    samples: list[dict[str, object]],
    *,
    confirm: float = CONFIRM_THRESHOLD,
    possible: float = POSSIBLE_THRESHOLD,
) -> FaceStep | None:
    """Confirm the invited person from three strong frames, or search once the frames stay weak."""
    faces = [sample for sample in samples if sample.get("kind") == "face"]
    empties = [sample for sample in samples if sample.get("kind") == "empty"]
    confirms = [sample for sample in faces if (_score(sample) or -1) >= confirm]
    weaks = [sample for sample in faces if _score(sample) is None or (_score(sample) or 0) < possible]
    if len(confirms) >= USABLE_TARGET:
        return FaceStep("confirmed", _median([_score(sample) or 0 for sample in confirms]))
    if len(weaks) >= USABLE_TARGET and not confirms:
        return _search_step(weaks)
    gave_up = len(empties) >= EMPTY_LIMIT and len(faces) < USABLE_TARGET
    if len(faces) >= USABLE_LIMIT or gave_up:
        if not faces:
            return FaceStep("no_face")
        if confirms and len(confirms) >= len(weaks):
            return FaceStep("confirmed", _median([_score(sample) or 0 for sample in confirms]))
        if weaks and len(weaks) >= len(confirms):
            return _search_step(weaks)
        scores = [_score(sample) for sample in faces if _score(sample) is not None]
        return FaceStep("uncertain", _median(scores) if scores else None)
    return None


def stored_samples(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop the face vectors once a conclusion no longer needs them."""
    return [{key: value for key, value in sample.items() if key != "embedding"} for sample in samples]


def _search_step(samples: list[dict[str, object]]) -> FaceStep:
    chosen = max(samples, key=lambda sample: _optional_float(sample.get("det_score")) or 0.0)
    return FaceStep("search", _score(chosen), _embedding(chosen))


def _score(sample: dict[str, object]) -> float | None:
    return _optional_float(sample.get("invited_similarity"))


def _embedding(sample: dict[str, object]) -> list[float] | None:
    raw = sample.get("embedding")
    if not isinstance(raw, list) or not raw:
        return None
    values: list[float] = []
    for item in raw:
        number = _optional_float(item)
        if number is None:
            return None
        values.append(number)
    return values


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def identification_message(
    status: str,
    *,
    invited_name: str,
    matched_name: str | None,
    hint_name: str | None,
    ambiguous: bool,
) -> str:
    """Say the identity outcome in words. A weak match is never described as a person."""
    invited = invited_name.strip() or "the invited candidate"
    if status == "consent_required":
        return "The candidate has not agreed to face identification. No identity is assumed."
    if status == "pending":
        return "No face check yet. Waiting for a camera frame. No identity is assumed."
    if status == "checking":
        return "Checking identity."
    if status == "no_face":
        return "No face was found in the camera frame. No identity is assumed."
    if status == "no_match":
        return "This face does not match a stored candidate photo. No identity is assumed."
    if status == "low_confidence" and ambiguous:
        return "Two stored photos are too close to tell apart. No identity is assumed."
    if status == "low_confidence":
        if hint_name and hint_name.strip():
            return f"Closest stored record is {hint_name.strip()}, but the match is too weak to confirm an identity."
        return "The closest stored photo is not close enough to confirm an identity."
    if status == "confirmed":
        return f"This face matches the invited candidate, {invited}."
    if status == "other_candidate":
        other = matched_name.strip() if matched_name and matched_name.strip() else "another stored candidate"
        return f"This face does not match {invited}. It matches {other}."
    return "No identity is assumed."


def decode_frame(payload: str, *, max_bytes: int = 1_500_000) -> bytes:
    """Decode one camera frame. Data URLs are accepted."""
    cleaned = payload.strip()
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1]
    try:
        raw = base64.b64decode(cleaned, validate=True)
    except Exception as exc:
        raise ValueError("The camera frame could not be read.") from exc
    if not raw:
        raise ValueError("The camera frame could not be read.")
    if len(raw) > max_bytes:
        raise ValueError("The camera frame is too large.")
    return raw
