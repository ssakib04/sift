import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_llm, require_recruiter
from app.core.config import Settings
from app.core.database import SessionFactory, get_session
from app.core.llm_fallback import FallbackLLMManager
from app.core.session_tokens import InvalidSessionToken, SessionClaims, decode_session_token
from app.schemas.interview import (
    AnalysisRead,
    CandidateOpenRequest,
    CopilotRead,
    IceServerRead,
    OpenedSessionRead,
    RecruiterOpenRequest,
    SessionDetailRead,
    SessionStatusRead,
    StartInterviewRequest,
    TranscriptTurnRead,
)
from app.services.interview_rooms import signal_hub
from app.services.interview_rules import InterviewError, assert_own_voice, can_store_audio, chunk_window
from app.services.interview_sessions import (
    OpenedSession,
    audio_status,
    end_interview,
    interview_copilot,
    list_transcript,
    open_candidate_session,
    open_recruiter_session,
    read_analysis,
    session_detail,
    start_interview,
    store_transcript_line,
)
from app.services.interview_speech import AudioTranscriptionError, get_transcriber

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/interview-sessions")
_bearer = HTTPBearer(auto_error=False)


def _host(request: Request) -> str:
    raw = request.headers.get("host", "")
    return raw.split(":")[0].strip()


def _claims(
    credentials: HTTPAuthorizationCredentials | None,
    settings: Settings,
) -> SessionClaims:
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


def _match(claims: SessionClaims, session_id: UUID) -> None:
    if claims.session_id != session_id:
        raise InterviewError("INTERVIEW_FORBIDDEN", "This link does not match the interview.", 403)


def _http(exc: InterviewError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error_code": exc.code, "message": exc.message})


def _opened_read(opened: OpenedSession) -> OpenedSessionRead:
    return OpenedSessionRead(
        session_id=opened.session_id,
        token=opened.token,
        role=opened.role,
        status=opened.status,
        job_title=opened.job_title,
        company_name=opened.company_name,
        ice_servers=[IceServerRead(**server) for server in opened.ice_servers],
        livekit_url=opened.livekit_url,
        livekit_token=opened.livekit_token,
    )


async def _current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_app_settings),
) -> SessionClaims:
    return _claims(credentials, settings)


@router.post("", response_model=OpenedSessionRead)
async def open_candidate(
    body: CandidateOpenRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> OpenedSessionRead:
    try:
        opened = await open_candidate_session(db, settings, body.token, _host(request))
    except InterviewError as exc:
        raise _http(exc) from exc
    if opened is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "INVITE_NOT_FOUND", "message": "This invitation link is not valid."},
        )
    return _opened_read(opened)


@router.post("/recruiter", response_model=OpenedSessionRead)
async def open_recruiter(
    body: RecruiterOpenRequest,
    request: Request,
    _authorized: None = Depends(require_recruiter),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> OpenedSessionRead:
    try:
        opened = await open_recruiter_session(db, settings, body.candidate_id, _host(request))
    except InterviewError as exc:
        raise _http(exc) from exc
    if opened is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "SESSION_NOT_FOUND", "message": "This candidate does not have an interview."},
        )
    return _opened_read(opened)


@router.get("/{session_id}", response_model=SessionDetailRead)
async def read_session(
    session_id: UUID,
    request: Request,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> SessionDetailRead:
    try:
        _match(claims, session_id)
        detail = await session_detail(db, settings, claims, _host(request))
    except InterviewError as exc:
        raise _http(exc) from exc
    return SessionDetailRead(
        session_id=detail.session_id,
        role=detail.role,
        status=detail.status,
        job_title=detail.job_title,
        company_name=detail.company_name,
        ice_servers=[IceServerRead(**server) for server in detail.ice_servers],
        livekit_url=detail.livekit_url,
        livekit_token=detail.livekit_token,
        consented_at=detail.consented_at,
        started_at=detail.started_at,
        ended_at=detail.ended_at,
    )


@router.get("/{session_id}/status", response_model=SessionStatusRead)
async def read_status(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> SessionStatusRead:
    del settings
    try:
        _match(claims, session_id)
        detail = await session_detail(db, get_app_settings(), claims, "")
    except InterviewError as exc:
        raise _http(exc) from exc
    return SessionStatusRead(
        session_id=detail.session_id,
        status=detail.status,
        consented_at=detail.consented_at,
        started_at=detail.started_at,
        ended_at=detail.ended_at,
    )


@router.post("/{session_id}/start", response_model=SessionStatusRead)
async def start_session(
    session_id: UUID,
    body: StartInterviewRequest,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> SessionStatusRead:
    try:
        _match(claims, session_id)
        await start_interview(db, claims, consent=body.consent)
        detail = await session_detail(db, get_app_settings(), claims, "")
    except InterviewError as exc:
        raise _http(exc) from exc
    return SessionStatusRead(
        session_id=detail.session_id,
        status=detail.status,
        consented_at=detail.consented_at,
        started_at=detail.started_at,
        ended_at=detail.ended_at,
    )


@router.post("/{session_id}/end", response_model=SessionStatusRead)
async def end_session(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> SessionStatusRead:
    try:
        _match(claims, session_id)
        await end_interview(db, llm, claims)
        detail = await session_detail(db, get_app_settings(), claims, "")
    except InterviewError as exc:
        raise _http(exc) from exc
    return SessionStatusRead(
        session_id=detail.session_id,
        status=detail.status,
        consented_at=detail.consented_at,
        started_at=detail.started_at,
        ended_at=detail.ended_at,
    )


@router.get("/{session_id}/transcript", response_model=list[TranscriptTurnRead])
async def read_transcript(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> list[TranscriptTurnRead]:
    try:
        _match(claims, session_id)
        segments = await list_transcript(db, claims)
    except InterviewError as exc:
        raise _http(exc) from exc
    return [
        TranscriptTurnRead(
            id=segment.id,
            speaker=segment.speaker,
            start_time=segment.start_time,
            end_time=segment.end_time,
            text=segment.text,
            confidence=segment.confidence,
        )
        for segment in segments
    ]


@router.get("/{session_id}/copilot", response_model=CopilotRead)
async def read_copilot(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> CopilotRead:
    try:
        _match(claims, session_id)
        draft = await interview_copilot(db, llm, claims)
    except InterviewError as exc:
        raise _http(exc) from exc
    return CopilotRead(explored=draft.explored, gaps=draft.gaps, suggested_question=draft.suggested_question)


@router.get("/{session_id}/analysis", response_model=AnalysisRead)
async def read_session_analysis(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> AnalysisRead:
    try:
        _match(claims, session_id)
        analysis = await read_analysis(db, claims)
    except InterviewError as exc:
        raise _http(exc) from exc
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ANALYSIS_PENDING", "message": "The interview analysis is not ready."},
        )
    return AnalysisRead(
        relevance=analysis.relevance,
        technical_accuracy=analysis.technical_accuracy,
        completeness=analysis.completeness,
        articulation=analysis.articulation,
        gaps=list(analysis.gaps or []),
        summary=analysis.summary,
        llm_tier=analysis.llm_tier,
        fallback_used=analysis.fallback_used,
    )


@router.websocket("/{session_id}/signal")
async def signal_socket(websocket: WebSocket, session_id: UUID) -> None:
    await websocket.accept()
    claims = await _socket_claims(websocket, session_id)
    if claims is None:
        return
    role = claims.role
    room_id = str(session_id)
    await signal_hub.join(room_id, role, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                await signal_hub.relay(room_id, role, message)
    except WebSocketDisconnect:
        pass
    finally:
        await signal_hub.leave(room_id, role, notify=True)


@router.websocket("/{session_id}/audio")
async def audio_socket(websocket: WebSocket, session_id: UUID) -> None:
    await websocket.accept()
    claims = await _socket_claims(websocket, session_id)
    if claims is None:
        return
    pending: dict[str, object] | None = None
    try:
        while True:
            incoming = await websocket.receive()
            if incoming["type"] == "websocket.disconnect":
                break
            text = incoming.get("text")
            data = incoming.get("bytes")
            if isinstance(text, str):
                pending = _chunk_header(claims, text)
            elif isinstance(data, bytes) and pending is not None:
                header = pending
                pending = None
                await _store_chunk(websocket, claims, header, data)
    except WebSocketDisconnect:
        return


async def _socket_claims(websocket: WebSocket, session_id: UUID) -> SessionClaims | None:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        message = json.loads(raw)
    except (asyncio.TimeoutError, WebSocketDisconnect, json.JSONDecodeError):
        await websocket.close(code=1008)
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        await websocket.close(code=1008)
        return None
    token = message.get("token")
    if not isinstance(token, str):
        await websocket.close(code=1008)
        return None
    try:
        claims = decode_session_token(token, get_app_settings().jwt_secret)
    except InvalidSessionToken:
        await websocket.close(code=1008)
        return None
    if claims.session_id != session_id:
        await websocket.close(code=1008)
        return None
    return claims


def _chunk_header(claims: SessionClaims, raw: str) -> dict[str, object] | None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict) or message.get("type") != "chunk":
        return None
    speaker = message.get("speaker")
    if not isinstance(speaker, str):
        return None
    try:
        owned = assert_own_voice(claims.role, speaker)
        start, end = chunk_window(message.get("start_time"), message.get("end_time"))
    except InterviewError:
        return None
    return {"speaker": owned, "start_time": start, "end_time": end}


async def _store_chunk(websocket: WebSocket, claims: SessionClaims, header: dict[str, object], data: bytes) -> None:
    async with SessionFactory() as db:
        try:
            status = await audio_status(db, claims)
        except InterviewError:
            await _send(websocket, {"type": "ignored"})
            return
        if not can_store_audio(status):
            await _send(websocket, {"type": "waiting-for-consent"})
            return
        try:
            text, confidence = await asyncio.to_thread(get_transcriber().transcribe, data)
        except AudioTranscriptionError:
            await _send(websocket, {"type": "transcription-unavailable"})
            return
        try:
            await store_transcript_line(
                db,
                claims,
                speaker=str(header["speaker"]),
                start_time=float(header["start_time"]),
                end_time=float(header["end_time"]),
                text=text,
                confidence=confidence,
            )
        except InterviewError as exc:
            await _send(websocket, {"type": "waiting-for-consent" if exc.code == "CONSENT_REQUIRED" else "ignored"})
            return
    await _send(websocket, {"type": "stored"})


async def _send(websocket: WebSocket, payload: dict[str, str]) -> None:
    try:
        await websocket.send_json(payload)
    except Exception as exc:
        logger.warning("audio_reply_failed error_type=%s", type(exc).__name__)
