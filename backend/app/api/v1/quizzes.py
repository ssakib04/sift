from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_llm, require_recruiter
from app.core.config import Settings
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.core.session_tokens import InvalidSessionToken, SessionClaims, decode_session_token
from app.schemas.quiz import CandidateQuizRead, QuizSubmitRequest, RecruiterQuizRead
from app.services.quiz_service import (
    QuizError,
    open_candidate_quiz,
    read_candidate_quiz,
    read_recruiter_quiz,
    submit_candidate_quiz,
)

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def _http(exc: QuizError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error_code": exc.code, "message": exc.message})


def _claims(credentials: HTTPAuthorizationCredentials | None, settings: Settings) -> SessionClaims:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "TOKEN_INVALID", "message": "This interview link is not valid."},
        )
    try:
        return decode_session_token(credentials.credentials, settings.jwt_secret)
    except InvalidSessionToken as exc:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "TOKEN_INVALID", "message": "This interview link is not valid."},
        ) from exc


async def _current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_app_settings),
) -> SessionClaims:
    return _claims(credentials, settings)


@router.post("/interview-sessions/{session_id}/quiz", response_model=CandidateQuizRead)
async def open_quiz(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> CandidateQuizRead:
    try:
        return await open_candidate_quiz(db, llm, claims, session_id)
    except QuizError as exc:
        raise _http(exc) from exc


@router.get("/interview-sessions/{session_id}/quiz", response_model=CandidateQuizRead)
async def read_quiz(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> CandidateQuizRead:
    try:
        return await read_candidate_quiz(db, claims, session_id)
    except QuizError as exc:
        raise _http(exc) from exc


@router.post("/interview-sessions/{session_id}/quiz/submit", response_model=CandidateQuizRead)
async def submit_quiz(
    session_id: UUID,
    body: QuizSubmitRequest,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> CandidateQuizRead:
    try:
        return await submit_candidate_quiz(db, claims, session_id, body)
    except QuizError as exc:
        raise _http(exc) from exc


@router.get("/candidates/{candidate_id}/quiz", response_model=RecruiterQuizRead)
async def read_candidate_result(
    candidate_id: UUID,
    _authorized: None = Depends(require_recruiter),
    db: AsyncSession = Depends(get_session),
) -> RecruiterQuizRead:
    try:
        return await read_recruiter_quiz(db, candidate_id)
    except QuizError as exc:
        raise _http(exc) from exc
