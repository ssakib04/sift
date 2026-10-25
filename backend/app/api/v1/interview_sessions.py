import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_llm, require_recruiter
from app.core.config import Settings
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.core.session_tokens import InvalidSessionToken, SessionClaims, decode_session_token
from app.schemas.interview import (
    AnalysisRead,
    JustificationRead,
    QAPairRead,
    CandidateOpenRequest,
    CopilotAskRead,
    CopilotAskRequest,
    CopilotRead,
    IdentificationAck,
    IdentificationFrameRequest,
    IdentificationRead,
    ProfileOverviewRead,
    IceServerRead,
    OpenedSessionRead,
    PracticeSessionRead,
    RecruiterOpenRequest,
    SessionDetailRead,
    SessionStatusRead,
    StartInterviewRequest,
    TranscriptTurnRead,
)
from app.services.identification import (
    IdentificationView,
    admit_candidate,
    identify_frame,
    read_identification,
    record_face_consent,
)
from app.services.interview_practice import open_practice_session
from app.services.interview_rooms import signal_hub
from app.services.interview_rules import InterviewError
from app.services.interview_sessions import (
    OpenedSession,
    ask_interview_copilot,
    end_interview,
    interview_copilot,
    list_transcript,
    open_candidate_session,
    open_recruiter_session,
    read_analysis,
    session_detail,
    start_interview,
)

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


@router.post("/practice", response_model=PracticeSessionRead)
async def open_practice(
    request: Request,
    _authorized: None = Depends(require_recruiter),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> PracticeSessionRead:
    try:
        opened, guest_url = await open_practice_session(db, settings, _host(request))
    except InterviewError as exc:
        raise _http(exc) from exc
    payload = _opened_read(opened)
    return PracticeSessionRead(**payload.model_dump(), guest_url=guest_url)


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
        processing_status=detail.processing_status,
        biometric_consented_at=detail.biometric_consented_at,
        conductor=detail.conductor,
        candidate_id=detail.candidate_id,
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
        await start_interview(db, claims, consent=body.consent, biometric_consent=body.biometric_consent)
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


@router.post("/{session_id}/identification", response_model=IdentificationAck)
async def check_identity(
    session_id: UUID,
    body: IdentificationFrameRequest,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> IdentificationAck:
    try:
        _match(claims, session_id)
        view = await identify_frame(db, settings, claims, body.image_base64)
    except InterviewError as exc:
        raise _http(exc) from exc
    return IdentificationAck(
        status=view.status,
        concluded=view.concluded,
        sample_count=view.sample_count,
        sample_limit=view.sample_limit,
        can_join=view.can_join,
    )


@router.get("/{session_id}/identification", response_model=IdentificationRead)
async def read_identity(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> IdentificationRead:
    try:
        _match(claims, session_id)
        view = await read_identification(db, claims)
    except InterviewError as exc:
        raise _http(exc) from exc
    return _identification_read(view)


def _identification_read(view: IdentificationView) -> IdentificationRead:
    profile = None
    if view.profile is not None:
        profile = ProfileOverviewRead(
            candidate_id=view.profile.candidate_id,
            full_name=view.profile.full_name,
            headline=view.profile.headline,
            skills=view.profile.skills,
            pre_interview_score=view.profile.pre_interview_score,
            probe_areas=view.profile.probe_areas,
        )
    return IdentificationRead(
        status=view.status,
        message=view.message,
        similarity=view.similarity,
        invited_similarity=view.invited_similarity,
        invited_name=view.invited_name,
        matched_name=view.matched_name,
        hint_name=view.hint_name,
        profile=profile,
        concluded=view.concluded,
        sample_count=view.sample_count,
        sample_limit=view.sample_limit,
        required=view.required,
        can_join=view.can_join,
        admitted=view.admitted,
    )


@router.post("/{session_id}/identification/consent", response_model=IdentificationRead)
async def consent_identity(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> IdentificationRead:
    try:
        _match(claims, session_id)
        view = await record_face_consent(db, claims)
    except InterviewError as exc:
        raise _http(exc) from exc
    return _identification_read(view)


@router.post("/{session_id}/identification/admit", response_model=IdentificationRead)
async def admit_identity(
    session_id: UUID,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
) -> IdentificationRead:
    try:
        _match(claims, session_id)
        view = await admit_candidate(db, claims)
    except InterviewError as exc:
        raise _http(exc) from exc
    return _identification_read(view)


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
            is_final=segment.is_final,
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
    return CopilotRead(
        explored=draft.explored,
        gaps=draft.gaps,
        suggested_question=draft.suggested_question,
        profile_available=draft.profile_available,
    )


@router.post("/{session_id}/copilot", response_model=CopilotAskRead)
async def ask_session_copilot(
    session_id: UUID,
    body: CopilotAskRequest,
    claims: SessionClaims = Depends(_current_claims),
    db: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> CopilotAskRead:
    try:
        _match(claims, session_id)
        answer = await ask_interview_copilot(db, llm, claims, body.question)
    except InterviewError as exc:
        raise _http(exc) from exc
    return CopilotAskRead(
        reply=answer.reply,
        questions=answer.questions,
        profile_available=answer.profile_available,
    )


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
        discrepancies=list(analysis.discrepancies or []),
        summary=analysis.summary,
        justifications=[
            JustificationRead(claim=str(item.get("claim") or ""), citation=str(item.get("citation") or ""))
            for item in analysis.justifications or []
            if isinstance(item, dict)
        ],
        pairs=[
            QAPairRead(
                pair_id=pair.pair_id,
                question=pair.question,
                answer=pair.answer,
                intent=pair.intent,
                citation=pair.citation,
                query_ids=list(pair.query_ids or []),
                relevance=pair.relevance,
                technical_accuracy=pair.technical_accuracy,
                completeness=pair.completeness,
                articulation=pair.articulation,
            )
            for pair in sorted(analysis.pairs, key=lambda item: item.sequence)
        ],
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
