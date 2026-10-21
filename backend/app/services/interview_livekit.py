import logging
from datetime import timedelta

from livekit.api import AccessToken, CreateAgentDispatchRequest, LiveKitAPI, VideoGrants

from app.core.config import Settings
from app.services.interview_rules import InterviewError

logger = logging.getLogger(__name__)
TRANSCRIBER_AGENT_NAME = "sift-transcriber"
INTERVIEWER_AGENT_NAME = "sift-interviewer"


def issue_livekit_token(settings: Settings, *, room: str, role: str) -> tuple[str, str]:
    """Mint a join token for the Sift interview room. The media server never sees the API secret."""
    url = settings.livekit_url.strip()
    api_key = settings.livekit_api_key.strip()
    api_secret = settings.livekit_api_secret.strip()
    if not url.startswith("wss://") or not api_key or not api_secret:
        raise InterviewError("INTERVIEW_UNAVAILABLE", "The video service is not configured.", 503)
    if role not in {"candidate", "recruiter"} or not room:
        raise InterviewError("INTERVIEW_FORBIDDEN", "This link does not match the interview.", 403)
    granted = (
        AccessToken(api_key, api_secret)
        .with_identity(role)
        .with_name("Interviewer" if role == "recruiter" else "Candidate")
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
            )
        )
        .with_ttl(timedelta(minutes=max(settings.jwt_ttl_minutes, 1)))
        .to_jwt()
    )
    return url, granted


def room_agent_name(settings: Settings, *, recruiter_present: bool) -> str:
    """The recruiter conducts when they are already in the room. Otherwise the agent does."""
    if settings.ai_interviewer_enabled and not recruiter_present:
        return INTERVIEWER_AGENT_NAME
    return TRANSCRIBER_AGENT_NAME


def transcriber_dispatch(room: str) -> CreateAgentDispatchRequest:
    """Ask LiveKit to send the transcriber into this interview room."""
    return CreateAgentDispatchRequest(agent_name=TRANSCRIBER_AGENT_NAME, room=room, metadata=room)


def room_agent_dispatch(settings: Settings, room: str, *, recruiter_present: bool) -> CreateAgentDispatchRequest:
    return CreateAgentDispatchRequest(
        agent_name=room_agent_name(settings, recruiter_present=recruiter_present),
        room=room,
        metadata=room,
    )


def _http_url(livekit_url: str) -> str:
    if livekit_url.startswith("wss://"):
        return "https://" + livekit_url.removeprefix("wss://")
    if livekit_url.startswith("ws://"):
        return "http://" + livekit_url.removeprefix("ws://")
    return livekit_url


async def dispatch_transcriber(settings: Settings, room: str) -> None:
    await _dispatch(settings, transcriber_dispatch(room))


async def room_has_recruiter(settings: Settings, room: str) -> bool:
    """True when the human interviewer has already joined this LiveKit room."""
    url = settings.livekit_url.strip()
    api_key = settings.livekit_api_key.strip()
    api_secret = settings.livekit_api_secret.strip()
    if not url.startswith("wss://") or not api_key or not api_secret:
        return False
    from livekit.api import ListParticipantsRequest

    client = LiveKitAPI(_http_url(url), api_key, api_secret)
    try:
        listed = await client.room.list_participants(ListParticipantsRequest(room=room))
    except Exception:
        logger.info("room_participants_unavailable room=%s", room)
        return False
    finally:
        await client.aclose()
    participants = getattr(listed, "participants", []) or []
    return any(getattr(person, "identity", "") == "recruiter" for person in participants)


async def dispatch_room_agent(settings: Settings, room: str, *, recruiter_present: bool) -> None:
    await _dispatch(settings, room_agent_dispatch(settings, room, recruiter_present=recruiter_present))


async def _dispatch(settings: Settings, request: CreateAgentDispatchRequest) -> None:
    url = settings.livekit_url.strip()
    api_key = settings.livekit_api_key.strip()
    api_secret = settings.livekit_api_secret.strip()
    if not url.startswith("wss://") or not api_key or not api_secret:
        raise InterviewError("INTERVIEW_UNAVAILABLE", "The video service is not configured.", 503)
    client = LiveKitAPI(_http_url(url), api_key, api_secret)
    try:
        await client.agent_dispatch.create_dispatch(request)
    finally:
        await client.aclose()
