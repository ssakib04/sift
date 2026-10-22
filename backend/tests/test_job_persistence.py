import uuid

import pytest
from sqlalchemy import delete

from app.core.config import Settings
from app.core.database import SessionFactory
from app.core.llm_fallback import FallbackLLMManager
from app.models.job import Job
from app.schemas.job import JobCreateRequest, JobVersionUpdate
from app.services.job_rules import ChecklistLockedError
from app.services.job_service import approve_version, create_job, open_next_version, update_draft
from app.services.postajob import PublishResult, mailbox_apply_url
from tests.checklist_factory import sample_queries


class RecordingPoster:
    def __init__(self) -> None:
        self.requests = []

    async def publish(self, request: object) -> PublishResult:
        self.requests.append(request)
        return PublishResult(external_id="camp-1", status="live")


class FixedRetriever:
    async def search(self, query: str, limit: int = 5) -> list[str]:
        del query, limit
        return ["Remote work requires manager approval."]


class ScriptedProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        import json

        self.calls += 1
        if self.calls == 1:
            return json.dumps(
                {
                    "description": (
                        "We are hiring a Senior Python Engineer to design policy-compliant services. "
                        "Remote work requires manager approval and the team ships FastAPI in production."
                    )
                }
            )
        return json.dumps({"queries": sample_queries()})


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        postajob_api_key="test-key",
        public_app_url="http://localhost:3000",
        company_name="Sift",
        company_country="Bangladesh",
    )


@pytest.mark.asyncio
async def test_approval_freezes_checklist_and_posts_without_exposing_scores() -> None:
    settings = _settings()
    provider = ScriptedProvider()
    llm = FallbackLLMManager(provider, provider, provider)
    poster = RecordingPoster()
    request = JobCreateRequest(
        title=f"Persistence {uuid.uuid4().hex[:8]}",
        seniority="Senior",
        required_skills=["Python"],
        preferred_skills=["pgvector"],
        qualifications="Bachelor degree",
        minimum_years=3,
    )
    try:
        async with SessionFactory() as session:
            await session.connection()
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    job_id = None
    try:
        async with SessionFactory() as session:
            created = await create_job(
                session,
                request,
                llm=llm,
                retriever=FixedRetriever(),
                settings=settings,
            )
            job_id = created.id
            approved = await approve_version(session, created.id, 1, poster=poster, settings=settings)
            locked = approved.versions[0]
            assert locked.status == "locked"
            assert locked.posting_status == "live"
            assert locked.external_posting_id == "camp-1"
            assert poster.requests
            assert poster.requests[0].apply_url == mailbox_apply_url(settings.apply_to_address, created.mail_subject)
            assert "/careers/" not in poster.requests[0].apply_url
            assert "age_range" not in poster.requests[0].model_dump()
            with pytest.raises(ChecklistLockedError):
                await update_draft(
                    session,
                    created.id,
                    1,
                    JobVersionUpdate(description="B" * 120),
                    settings,
                )
            revised = await open_next_version(session, created.id, settings)
            assert [version.version_number for version in revised.versions] == [1, 2]
            assert revised.versions[0].status == "locked"
            assert revised.versions[1].status == "draft"
            assert revised.versions[0].queries[0].question == revised.versions[1].queries[0].question
    finally:
        if job_id is not None:
            async with SessionFactory() as session:
                await session.execute(delete(Job).where(Job.id == job_id))
                await session.commit()
