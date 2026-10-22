import json

import httpx
import pytest

from app.services.postajob import PostAJobPoster, PublishRequest, build_campaign_body, mailbox_apply_url


def _request() -> PublishRequest:
    return PublishRequest(
        title="Senior Python Engineer",
        description="A" * 120,
        apply_url="http://localhost:3000/careers/abc",
        contract="Full Time",
        category="Information Technology",
        company_name="Sift",
        company_country="Bangladesh",
        seniority="Senior",
        skills=["Python", "FastAPI"],
        version_id="version-1",
    )


def test_mailbox_apply_url_uses_the_subject() -> None:
    url = mailbox_apply_url("apply@sift.local", "Quantum Software Engineer")
    assert url == "mailto:apply@sift.local?subject=Quantum%20Software%20Engineer"
    assert "/careers/" not in url


def test_campaign_body_omits_age_targeting() -> None:
    body = build_campaign_body(_request())
    assert "age_range" not in body
    assert body["budget"] == 0
    assert body["url"] == "http://localhost:3000/careers/abc"
    assert body["client_id"] == "version-1"
    assert body["company_country"] == "Bangladesh"


@pytest.mark.asyncio
async def test_poster_creates_then_publishes() -> None:
    seen: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "POST":
            return httpx.Response(200, json={"ok": True, "campaign": {"_id": "camp-1", "status": "Draft"}})
        return httpx.Response(200, json={"ok": True, "campaign": {"_id": "camp-1", "status": "Live"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.postajob.io/v1") as client:
        poster = PostAJobPoster(api_key="test-key", base_url="https://api.postajob.io/v1", client=client)
        result = await poster.publish(_request())

    assert result.external_id == "camp-1"
    assert result.status == "live"
    assert seen[0][0] == "POST"
    assert seen[0][1].endswith("/campaign")
    assert seen[0][2] is not None and "age_range" not in seen[0][2]
    assert seen[1][0] == "PUT"
    assert seen[1][1].endswith("/campaign/publish/camp-1")
