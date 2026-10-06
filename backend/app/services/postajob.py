from typing import Protocol

import httpx
from pydantic import BaseModel

from app.core.config import Settings


class PublishRequest(BaseModel):
    title: str
    description: str
    apply_url: str
    contract: str
    category: str
    company_name: str
    company_country: str
    seniority: str
    skills: list[str]
    version_id: str


class PublishResult(BaseModel):
    external_id: str | None
    status: str
    detail: str | None = None


class PostAJobError(RuntimeError):
    """PostAJob rejected or failed a campaign publish."""


class JobPoster(Protocol):
    async def publish(self, request: PublishRequest) -> PublishResult:
        """Create and publish one campaign."""


def build_campaign_body(request: PublishRequest) -> dict[str, object]:
    return {
        "name": request.title,
        "title": request.title,
        "description": request.description,
        "url": request.apply_url,
        "contract": request.contract,
        "category": request.category,
        "company_name": request.company_name,
        "company_country": request.company_country,
        "experience": request.seniority,
        "skills": request.skills,
        "client_id": request.version_id,
        "budget": 0,
    }


class PostAJobPoster:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.postajob.io/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def publish(self, request: PublishRequest) -> PublishResult:
        body = build_campaign_body(request)
        headers = {"x-apikey": self._api_key, "Content-Type": "application/json"}
        if self._client is None:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._publish_with(client, body, headers)
        return await self._publish_with(self._client, body, headers)

    async def _publish_with(
        self,
        client: httpx.AsyncClient,
        body: dict[str, object],
        headers: dict[str, str],
    ) -> PublishResult:
        created = await client.post(f"{self._base_url}/campaign", headers=headers, json=body)
        if created.status_code >= 400:
            raise PostAJobError(f"campaign_create_failed:{created.status_code}")
        created_payload = created.json()
        campaign = created_payload.get("campaign") if isinstance(created_payload, dict) else None
        external_id = campaign.get("_id") if isinstance(campaign, dict) else None
        if not isinstance(external_id, str) or not external_id:
            raise PostAJobError("campaign_create_missing_id")
        published = await client.put(
            f"{self._base_url}/campaign/publish/{external_id}",
            headers=headers,
        )
        if published.status_code >= 400:
            raise PostAJobError(f"campaign_publish_failed:{published.status_code}")
        published_payload = published.json()
        published_campaign = (
            published_payload.get("campaign") if isinstance(published_payload, dict) else None
        )
        remote_status = "published"
        if isinstance(published_campaign, dict) and published_campaign.get("status"):
            remote_status = str(published_campaign["status"]).lower()
        return PublishResult(external_id=external_id, status=remote_status)


def poster_from_settings(settings: Settings, client: httpx.AsyncClient | None = None) -> PostAJobPoster:
    return PostAJobPoster(api_key=settings.postajob_api_key, base_url=settings.postajob_base_url, client=client)
