import math
import uuid

import pytest

from app.core.config import Settings
from app.models.candidate import FACE_DIMENSIONS
from app.services.face_embed import HashingFaceEmbedder, create_face_embedder
from app.services.face_identity import (
    USABLE_TARGET,
    EnrolledFace,
    IdentityDecision,
    append_face_sample,
    conclude_face_samples,
    cosine,
    decide_identity,
    decode_frame,
    identification_message,
    probe_areas,
    profile_from_attributes,
)
from app.services.identification import store_candidate_profile
from app.services.interview_rules import InterviewError, assert_candidate


def _axis(index: int) -> list[float]:
    values = [0.0] * FACE_DIMENSIONS
    values[index] = 1.0
    return values


def _mix(similarity: float, axis: int, other: int) -> list[float]:
    values = [0.0] * FACE_DIMENSIONS
    values[axis] = similarity
    values[other] = math.sqrt(1 - similarity * similarity)
    return values


def test_confirmed_match_prefers_the_invited_candidate() -> None:
    invited = uuid.uuid4()
    other = uuid.uuid4()
    decision = decide_identity(
        live=_axis(0),
        invited_id=invited,
        invited_embedding=_mix(0.8, 0, 1),
        gallery=[EnrolledFace(other, _mix(0.5, 0, 2))],
    )
    assert decision.status == "confirmed"
    assert decision.matched_candidate_id == invited
    assert decision.invited_similarity == pytest.approx(0.8)
    assert decision.ambiguous is False


def test_other_candidate_is_named_only_when_the_invited_face_does_not_match() -> None:
    invited = uuid.uuid4()
    other = uuid.uuid4()
    decision = decide_identity(
        live=_axis(0),
        invited_id=invited,
        invited_embedding=_mix(0.2, 0, 1),
        gallery=[EnrolledFace(other, _mix(0.84, 0, 2))],
    )
    assert decision.status == "other_candidate"
    assert decision.matched_candidate_id == other


def test_low_confidence_keeps_a_hint_without_confirming_identity() -> None:
    invited = uuid.uuid4()
    decision = decide_identity(
        live=_axis(0),
        invited_id=invited,
        invited_embedding=_mix(0.36, 0, 1),
        gallery=[],
    )
    assert decision.status == "low_confidence"
    assert decision.matched_candidate_id == invited
    assert decision.ambiguous is False


def test_close_high_scores_are_ambiguous_and_name_nobody() -> None:
    invited = uuid.uuid4()
    other = uuid.uuid4()
    decision = decide_identity(
        live=_axis(0),
        invited_id=invited,
        invited_embedding=_mix(0.80, 0, 1),
        gallery=[EnrolledFace(other, _mix(0.78, 0, 2))],
    )
    assert decision.status == "low_confidence"
    assert decision.matched_candidate_id is None
    assert decision.ambiguous is True


def test_no_face_and_no_match_never_assign_a_candidate() -> None:
    invited = uuid.uuid4()
    missing = decide_identity(
        live=None,
        invited_id=invited,
        invited_embedding=_axis(0),
        gallery=[],
    )
    distant = decide_identity(
        live=_axis(0),
        invited_id=invited,
        invited_embedding=_mix(0.1, 0, 1),
        gallery=[],
    )
    empty = decide_identity(live=_axis(0), invited_id=invited, invited_embedding=None, gallery=[])
    assert missing.status == "no_face"
    assert missing.matched_candidate_id is None
    assert distant.status == "no_match"
    assert distant.matched_candidate_id is None
    assert empty.status == "no_match"


def test_gallery_supplies_the_invited_face_when_it_was_not_passed_separately() -> None:
    invited = uuid.uuid4()
    decision = decide_identity(
        live=_axis(0),
        invited_id=invited,
        invited_embedding=None,
        gallery=[EnrolledFace(invited, _mix(0.9, 0, 1))],
    )
    assert decision.status == "confirmed"
    assert decision.invited_similarity == pytest.approx(0.9)


def test_short_embeddings_are_ignored() -> None:
    invited = uuid.uuid4()
    decision = decide_identity(
        live=_axis(0),
        invited_id=invited,
        invited_embedding=None,
        gallery=[EnrolledFace(uuid.uuid4(), [1.0, 0.0])],
    )
    assert decision.status == "no_match"


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        decide_identity(
            live=_axis(0),
            invited_id=uuid.uuid4(),
            invited_embedding=_axis(0),
            gallery=[],
            confirm=0.2,
            possible=0.4,
        )


def test_cosine_rejects_the_wrong_width() -> None:
    with pytest.raises(ValueError):
        cosine([1.0], [1.0])


def test_profile_headline_uses_the_latest_role_and_named_skills() -> None:
    headline, skills, years = profile_from_attributes(
        {
            "skills": ["React", " ", "FastAPI", 3],
            "experience_years": 4,
            "work_history": [{"title": "Frontend Engineer", "company": "Northwind", "summary": ""}],
        }
    )
    assert headline == "Frontend Engineer · Northwind"
    assert skills == ["React", "FastAPI"]
    assert years == 4
    fallback, _, stated = profile_from_attributes({"experience_years": 6})
    assert fallback == "6 years of experience"
    assert stated == 6


def test_probe_areas_keep_only_open_checklist_questions() -> None:
    rows = [("met", "Knows Python")] + [( "unmet", f"Question {index}") for index in range(6)]
    areas = probe_areas(rows)
    assert areas == [f"Question {index}" for index in range(5)]
    assert "Knows Python" not in areas


def _face(similarity: float, det_score: float, marker: float) -> dict[str, object]:
    samples = append_face_sample([], embedding=[marker], det_score=det_score, invited_similarity=similarity)
    return samples[0]


def test_three_strong_frames_confirm_without_waiting_for_more() -> None:
    samples = [_face(0.61, 0.9, 0.1), _face(0.7, 0.8, 0.2)]
    assert conclude_face_samples(samples) is None
    samples.append(_face(0.55, 0.7, 0.3))
    conclusion = conclude_face_samples(samples)
    assert conclusion is not None
    assert conclusion.action == "confirmed"
    assert conclusion.invited_similarity == pytest.approx(0.61)
    assert len(samples) == USABLE_TARGET


def test_empty_frames_do_not_vote_and_a_run_of_them_means_no_face() -> None:
    samples: list[dict[str, object]] = []
    for _ in range(5):
        samples = append_face_sample(samples, embedding=None)
    assert conclude_face_samples(samples) is None
    samples = append_face_sample(samples, embedding=None)
    conclusion = conclude_face_samples(samples)
    assert conclusion is not None
    assert conclusion.action == "no_face"
    assert append_face_sample(samples, embedding=None) == samples


def test_three_weak_frames_search_the_clearest_one() -> None:
    samples = [_face(0.1, 0.4, 1.0), _face(0.2, 0.95, 2.0), _face(0.05, 0.5, 3.0)]
    conclusion = conclude_face_samples(samples)
    assert conclusion is not None
    assert conclusion.action == "search"
    assert conclusion.embedding == [2.0]


def test_messages_refuse_to_treat_a_weak_result_as_an_identity() -> None:
    assert "No identity is assumed" in identification_message(
        "no_match", invited_name="Ada", matched_name=None, hint_name=None, ambiguous=False
    )
    assert "too weak" in identification_message(
        "low_confidence", invited_name="Ada", matched_name=None, hint_name="Grace", ambiguous=False
    )
    assert "too close" in identification_message(
        "low_confidence", invited_name="Ada", matched_name=None, hint_name="Grace", ambiguous=True
    )
    assert "matches the invited candidate, Ada" in identification_message(
        "confirmed", invited_name="Ada", matched_name="Ada", hint_name=None, ambiguous=False
    )
    assert "does not match Ada" in identification_message(
        "other_candidate", invited_name="Ada", matched_name="Grace", hint_name=None, ambiguous=False
    )
    assert "has not agreed" in identification_message(
        "consent_required", invited_name="Ada", matched_name=None, hint_name=None, ambiguous=False
    )


def test_decode_frame_accepts_a_data_url_and_rejects_empty_or_huge_payloads() -> None:
    import base64

    raw = b"jpeg-bytes"
    decoded = decode_frame("data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"))
    assert decoded == raw
    with pytest.raises(ValueError):
        decode_frame("not-base64")
    with pytest.raises(ValueError):
        decode_frame(base64.b64encode(b"x" * 20).decode("ascii"), max_bytes=8)


def _png(width: int, height: int, *, varied: bool, seed: int = 3) -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.new("RGB", (width, height))
    if varied:
        image.putdata(
            [((x * seed) % 256, (y * (seed + 2)) % 256, (x + y * seed) % 256) for y in range(height) for x in range(width)]
        )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_hashing_embedder_is_stable_and_rejects_photos_that_are_not_faces() -> None:
    embedder = HashingFaceEmbedder()
    photo = _png(80, 96, varied=True)
    first = embedder.embed(photo)
    second = embedder.embed(photo)
    other = embedder.embed(_png(80, 96, varied=True, seed=9))
    assert first is not None and second is not None and other is not None
    assert len(first.embedding) == FACE_DIMENSIONS
    assert cosine(first.embedding, second.embedding) == pytest.approx(1)
    assert cosine(first.embedding, other.embedding) < 0.999
    assert embedder.embed(_png(80, 80, varied=False)) is None
    assert embedder.embed(_png(16, 16, varied=True)) is None
    assert first.crop_jpeg.startswith(b"\xff\xd8")


def test_hashing_backend_does_not_load_insightface() -> None:
    embedder = create_face_embedder(Settings(_env_file=None, face_backend="hashing"))
    assert isinstance(embedder, HashingFaceEmbedder)


def test_stored_profile_keeps_headline_and_skills() -> None:
    candidate_id = uuid.uuid4()
    profile = store_candidate_profile(
        candidate_id,
        {"skills": ["SQL"], "work_history": [{"title": "Analyst", "company": "Sift"}]},
    )
    assert profile.candidate_id == candidate_id
    assert profile.headline == "Analyst · Sift"
    assert profile.skills == ["SQL"]


def test_only_the_candidate_camera_can_be_checked() -> None:
    assert_candidate("candidate")
    with pytest.raises(InterviewError) as exc:
        assert_candidate("recruiter")
    assert exc.value.code == "INTERVIEW_FORBIDDEN"
