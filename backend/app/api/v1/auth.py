from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.recruiter_auth import (
    InvalidRecruiterToken,
    RecruiterAuthNotConfigured,
    decode_recruiter_token,
    issue_recruiter_token,
    password_matches,
)
from app.schemas.auth import LoginRead, LoginRequest, RecruiterRead

router = APIRouter(prefix="/auth")
_bearer = HTTPBearer(auto_error=False)


def require_recruiter(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "RECRUITER_AUTH_REQUIRED", "message": "Sign in to continue."},
        )
    try:
        decode_recruiter_token(credentials.credentials, settings.jwt_secret)
    except InvalidRecruiterToken as exc:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "RECRUITER_AUTH_REQUIRED", "message": "Sign in to continue."},
        ) from exc


@router.post("/login", response_model=LoginRead)
def login(body: LoginRequest, settings: Settings = Depends(get_settings)) -> LoginRead:
    try:
        matches = password_matches(body.password, settings.recruiter_password)
    except RecruiterAuthNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "AUTH_NOT_CONFIGURED", "message": "Recruiter sign-in is not configured."},
        ) from exc
    if not matches:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "RECRUITER_AUTH_REQUIRED", "message": "That password is not correct."},
        )
    try:
        token = issue_recruiter_token(secret=settings.jwt_secret, ttl_minutes=settings.jwt_ttl_minutes)
    except InvalidRecruiterToken as exc:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "AUTH_NOT_CONFIGURED", "message": "Recruiter sign-in is not configured."},
        ) from exc
    return LoginRead(token=token, role="recruiter")


@router.get("/me", response_model=RecruiterRead)
def me(_authorized: None = Depends(require_recruiter)) -> RecruiterRead:
    return RecruiterRead(role="recruiter")
