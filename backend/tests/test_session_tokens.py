import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.session_tokens import InvalidSessionToken, decode_session_token, issue_session_token


def test_session_token_carries_only_the_interview_claims() -> None:
    candidate_id = uuid.uuid4()
    job_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(UTC)
    token = issue_session_token(
        role="candidate",
        candidate_id=candidate_id,
        job_id=job_id,
        session_id=session_id,
        secret="test-secret",
        ttl_minutes=30,
        now=now,
    )
    payload = jwt.decode(token, "test-secret", algorithms=["HS256"])
    assert set(payload) == {"role", "candidate_id", "job_id", "session_id", "exp"}
    claims = decode_session_token(token, "test-secret")
    assert claims.role == "candidate"
    assert claims.candidate_id == candidate_id
    assert claims.job_id == job_id
    assert claims.session_id == session_id
    assert "score" not in token.casefold()


def test_session_token_rejects_a_different_secret() -> None:
    token = issue_session_token(
        role="recruiter",
        candidate_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret="test-secret",
        ttl_minutes=5,
    )
    with pytest.raises(InvalidSessionToken):
        decode_session_token(token, "other-secret")


def test_session_token_rejects_an_expired_token() -> None:
    token = issue_session_token(
        role="candidate",
        candidate_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret="test-secret",
        ttl_minutes=5,
        now=datetime.now(UTC) - timedelta(hours=2),
    )
    with pytest.raises(InvalidSessionToken):
        decode_session_token(token, "test-secret")
