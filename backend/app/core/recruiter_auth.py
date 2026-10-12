import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import jwt

from app.core.session_tokens import InvalidSessionToken, decode_session_token


class InvalidRecruiterToken(Exception):
    """The recruiter sign-in token is missing, expired, or is an interview token."""


class RecruiterAuthNotConfigured(Exception):
    """No recruiter password is set, so sign-in is refused."""


def password_matches(provided: str, expected: str) -> bool:
    if not expected:
        raise RecruiterAuthNotConfigured
    provided_hash = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_hash = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(provided_hash, expected_hash)


def issue_recruiter_token(*, secret: str, ttl_minutes: int, now: datetime | None = None) -> str:
    if not secret:
        raise InvalidRecruiterToken
    issued_at = now or datetime.now(UTC)
    payload = {
        "role": "recruiter",
        "scope": "app",
        "exp": issued_at + timedelta(minutes=ttl_minutes),
    }
    encoded = jwt.encode(payload, secret, algorithm="HS256")
    if isinstance(encoded, bytes):
        return encoded.decode("ascii")
    return encoded


def decode_recruiter_token(token: str, secret: str) -> None:
    if not token or not secret:
        raise InvalidRecruiterToken
    try:
        decode_session_token(token, secret)
    except InvalidSessionToken:
        pass
    else:
        raise InvalidRecruiterToken
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidRecruiterToken from exc
    if set(payload) != {"role", "scope", "exp"}:
        raise InvalidRecruiterToken
    if payload.get("role") != "recruiter" or payload.get("scope") != "app":
        raise InvalidRecruiterToken
