import json

import httpx
import pytest

from app.services.postajob import PublishRequest
from app.services.telegram import TelegramError, TelegramPoster, build_channel_text


def _request() -> PublishRequest:
    return PublishRequest(
        title="Front End Developer",
        description="We are hiring a Front End Developer who can ship React interfaces for hiring workflows. " * 2,
        apply_url="http://localhost:3000/careers/version-1",
        contract="Full Time",
        category="Information Technology",
        company_name="Sift",
        company_country="Bangladesh",
        seniority="Mid-Level",
        skills=["React"],
        version_id="version-1",
    )


def test_channel_text_is_public_job_only() -> None:
    text = build_channel_text(_request())
    assert "Front End Developer" in text
    assert "Apply" in text
    assert "scoring_rubric" not in text
    assert "age_range" not in text
    assert "http://localhost:3000/careers/version-1" in text


def test_channel_text_includes_apply_mailbox_and_subject() -> None:
    request = _request().model_copy(
        update={"apply_email": "kazisadmansakib@gmail.com", "mail_subject": "Front End Developer"}
    )
    text = build_channel_text(request)
    assert "kazisadmansakib@gmail.com" in text
    assert "Subject: Front End Developer" in text


@pytest.mark.asyncio
async def test_poster_sends_one_channel_message() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.url.path == "/bottest-token/sendMessage"
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 12}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        poster = TelegramPoster(bot_token="test-token", chat_id="@siftjobs", client=client)
        result = await poster.publish(_request())

    assert result.status == "live"
    assert result.external_id == "12"
    assert result.detail == "https://t.me/siftjobs/12"
    assert seen[0]["chat_id"] == "@siftjobs"
    assert seen[0]["parse_mode"] == "HTML"
    assert "scoring_rubric" not in str(seen[0]["text"])


@pytest.mark.asyncio
async def test_poster_hides_transport_failures() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Forbidden: bot is not a member of the channel"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        poster = TelegramPoster(bot_token="test-token", chat_id="@siftjobs", client=client)
        with pytest.raises(TelegramError, match="not a member"):
            await poster.publish(_request())
