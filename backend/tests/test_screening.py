import uuid
from datetime import UTC, datetime

from app.models.candidate import Candidate
from app.services.screening import _to_candidate_read


def test_unscored_candidate_is_listed_without_a_rank() -> None:
    candidate = Candidate(
        id=uuid.uuid4(),
        job_version_id=uuid.uuid4(),
        email="ada@example.com",
        full_name="Ada Lovelace",
        content_sha256="abc",
        source_message_id="msg-1",
        created_at=datetime(2026, 10, 21, 8, 30, tzinfo=UTC),
    )
    candidate.parse_result = None
    candidate.snapshot = None
    candidate.magic_link = None
    candidate.quiz_attempt = None
    listed = _to_candidate_read(candidate)
    assert listed.rank is None
    assert listed.mcq_score is None
    assert listed.invited is False
    assert listed.email == "ada@example.com"
    assert listed.evaluations == []
    assert listed.has_photo is False
    assert listed.interview_status == ""
    assert listed.report_progress == {}
    assert listed.created_at == datetime(2026, 10, 21, 8, 30, tzinfo=UTC)
