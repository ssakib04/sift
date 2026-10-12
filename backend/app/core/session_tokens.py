from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt


class InvalidSessionToken(Exception):
    """The interview token is missing, expired, or signed with another secret."""


@dataclass(frozen=True)
class SessionClaims:
    role: str
    candidate_id: UUID
    job_id: UUID
    session_id: UUID


def issue_session_token(
    *,
    role: str,
    candidate_id: UUID,
    job_id: UUID,
    session_id: UUID,
    secret: str,
    ttl_minutes: int,
    now: datetime | None = None,
) -> str:
    """Sign the five interview claims. The secret stays in the signature."""
    if role not in {"candidate", "recruiter"}:
        raise InvalidSessionToken
    if not secret:
        raise InvalidSessionToken
    issued_at = now or datetime.now(UTC)
    payload = {
        "role": role,
        "candidate_id": str(candidate_id),
        "job_id": str(job_id),
        "session_id": str(session_id),
        "exp": issued_at + timedelta(minutes=ttl_minutes),
    }
    encoded = jwt.encode(payload, secret, algorithm="HS256")
    if isinstance(encoded, bytes):
        return encoded.decode("ascii")
    return encoded


def decode_session_token(token: str, secret: str) -> SessionClaims:
    if not token or not secret:
        raise InvalidSessionToken
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidSessionToken from exc
    role = payload.get("role")
    if role not in {"candidate", "recruiter"}:
        raise InvalidSessionToken
    expected = {"role", "candidate_id", "job_id", "session_id", "exp"}
    if set(payload) != expected:
        raise InvalidSessionToken
    try:
        return SessionClaims(
            role=role,
            candidate_id=UUID(str(payload["candidate_id"])),
            job_id=UUID(str(payload["job_id"])),
            session_id=UUID(str(payload["session_id"])),
        )
    except (TypeError, ValueError) as exc:
        raise InvalidSessionToken from exc
