import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.recruiter_auth import (
    InvalidRecruiterToken,
    RecruiterAuthNotConfigured,
    decode_recruiter_token,
    issue_recruiter_token,
    password_matches,
)
from app.core.session_tokens import issue_session_token


def test_password_match_rejects_a_different_length() -> None:
    assert password_matches("correct-horse", "correct-horse") is True
    assert password_matches("nope", "correct-horse") is False


def test_password_match_refuses_an_empty_configured_password() -> None:
    with pytest.raises(RecruiterAuthNotConfigured):
        password_matches("anything", "")


def test_recruiter_token_is_not_an_interview_token() -> None:
    secret = "test-secret-test-secret-test-secret"
    token = issue_recruiter_token(secret=secret, ttl_minutes=30, now=datetime.now(UTC))
    decode_recruiter_token(token, secret)
    interview = issue_session_token(
        role="recruiter",
        candidate_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret=secret,
        ttl_minutes=30,
    )
    with pytest.raises(InvalidRecruiterToken):
        decode_recruiter_token(interview, secret)


def test_recruiter_token_rejects_expiry() -> None:
    secret = "test-secret-test-secret-test-secret"
    token = issue_recruiter_token(
        secret=secret,
        ttl_minutes=5,
        now=datetime.now(UTC) - timedelta(hours=2),
    )
    with pytest.raises(InvalidRecruiterToken):
        decode_recruiter_token(token, secret)
