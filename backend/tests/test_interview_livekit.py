import pytest
from livekit.api import TokenVerifier

from app.core.config import Settings
from app.services.interview_livekit import issue_livekit_token
from app.services.interview_rules import InterviewError

_KEY = "APItestkeyvalue1"
_SECRET = "test-livekit-secret-test-livekit-secret"


def _settings(**overrides: str) -> Settings:
    values = {
        "livekit_url": "wss://sift.livekit.cloud",
        "livekit_api_key": _KEY,
        "livekit_api_secret": _SECRET,
        "jwt_ttl_minutes": 30,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_livekit_token_joins_only_that_interview_room() -> None:
    url, token = issue_livekit_token(_settings(), room="session-1", role="candidate")
    claims = TokenVerifier(_KEY, _SECRET).verify(token)
    assert url == "wss://sift.livekit.cloud"
    assert claims.identity == "candidate"
    assert claims.video is not None
    assert claims.video.room == "session-1"
    assert claims.video.room_join is True
    assert claims.video.can_publish is True
    assert claims.video.can_subscribe is True
    assert claims.video.can_publish_data is False


def test_livekit_token_rejects_a_different_secret() -> None:
    _url, token = issue_livekit_token(_settings(), room="session-1", role="recruiter")
    with pytest.raises(Exception):
        TokenVerifier(_KEY, "other-secret-other-secret-other").verify(token)


def test_livekit_token_refuses_an_unconfigured_project() -> None:
    with pytest.raises(InterviewError) as missing:
        issue_livekit_token(_settings(livekit_url=""), room="session-1", role="recruiter")
    assert missing.value.status_code == 503
