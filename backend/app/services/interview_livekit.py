from datetime import timedelta

from livekit.api import AccessToken, VideoGrants

from app.core.config import Settings
from app.services.interview_rules import InterviewError


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
