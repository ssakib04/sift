import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.config import Settings
from app.core.database import SessionFactory
from app.core.llm_fallback import FallbackLLMManager
from app.models.job import Job
from app.schemas.copilot import CopilotMessage
from app.schemas.job import JobRead, JobVersionRead
from app.services.copilot import PLANNER_SYSTEM, job_request_from_plan, plan_from_model_text, run_copilot_turn, summarize_jobs
from tests.checklist_factory import sample_queries


class PromptProvider:
    def __init__(self, description: str) -> None:
        self.description = description
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls += 1
        if system == PLANNER_SYSTEM:
            return json.dumps(
                {
                    "action": "create_job",
                    "message": "",
                    "job": {
                        "title": "Senior Python Engineer",
                        "seniority": "Senior",
                        "required_skills": ["Python", "FastAPI"],
                        "preferred_skills": ["LangGraph"],
                        "qualifications": "Bachelor in computer science",
                        "minimum_years": 4,
                        "category": "Software",
                    },
                }
            )
        if "Write a policy-compliant job description" in prompt:
            return json.dumps({"description": self.description})
        return json.dumps({"queries": sample_queries()})


class ReplyProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        return json.dumps({"action": "reply", "message": "What role should I draft?", "job": None})


class StaticRetriever:
    async def search(self, query: str, limit: int = 5) -> list[str]:
        del query, limit
        return ["Remote work requires manager approval."]


def _settings() -> Settings:
    return Settings(_env_file=None, public_app_url="http://localhost:3000", company_name="Sift", company_country="Bangladesh")


def test_missing_skills_become_a_question() -> None:
    plan = plan_from_model_text(json.dumps({"action": "create_job", "message": "", "job": {"title": "Analyst"}}))
    question = job_request_from_plan(plan)
    assert isinstance(question, str)
    assert "required skill" in question


def test_unknown_category_falls_back_to_information_technology() -> None:
    plan = plan_from_model_text(
        json.dumps(
            {
                "action": "create_job",
                "job": {"title": "Analyst", "required_skills": ["SQL"], "category": "Software"},
            }
        )
    )
    request = job_request_from_plan(plan)
    assert not isinstance(request, str)
    assert request.category == "Information Technology"
    assert request.seniority == "Mid-Level"


def test_job_summary_reports_status_without_rubrics() -> None:
    version_id = uuid4()
    job = JobRead(
        id=uuid4(),
        title="Backend Engineer",
        mail_subject="Backend Engineer",
        apply_email="careers@sift.local",
        created_at=datetime.now(UTC),
        versions=[
            JobVersionRead(
                id=version_id,
                version_number=1,
                status="draft",
                seniority="Mid-Level",
                required_skills=["Python"],
                preferred_skills=[],
                qualifications="Degree",
                minimum_years=2,
                technical_weight=0.5,
                experience_weight=0.3,
                qualification_weight=0.2,
                contract="Full Time",
                category="Information Technology",
                description="A" * 120,
                queries=[],
                llm_tier="claude",
                fallback_used=False,
                created_at=datetime.now(UTC),
                locked_at=None,
                posting_status=None,
                posting_detail=None,
                external_posting_id=None,
                apply_url=None,
            )
        ],
    )
    summary = summarize_jobs([job])
    assert "Backend Engineer, version 1, draft" in summary
    assert "scoring_rubric" not in summary


@pytest.mark.asyncio
async def test_reply_does_not_need_a_database() -> None:
    llm = FallbackLLMManager(ReplyProvider(), ReplyProvider(), ReplyProvider())
    result = await run_copilot_turn(
        None,
        [CopilotMessage(role="user", content="Hello")],
        llm=llm,
        retriever=StaticRetriever(),
        settings=_settings(),
    )
    assert result.job is None
    assert "role" in result.message


@pytest.mark.asyncio
async def test_copilot_creates_a_draft_through_workflow_one() -> None:
    description = (
        "We are hiring a Senior Python Engineer to build policy-compliant APIs. "
        "Remote work requires manager approval and the team ships FastAPI in production."
    )
    provider = PromptProvider(description)
    llm = FallbackLLMManager(provider, provider, provider)
    job_id = None
    try:
        async with SessionFactory() as session:
            await session.connection()
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    try:
        async with SessionFactory() as session:
            result = await run_copilot_turn(
                session,
                [CopilotMessage(role="user", content="Draft a senior Python engineer role requiring FastAPI.")],
                llm=llm,
                retriever=StaticRetriever(),
                settings=_settings(),
            )
            assert result.job is not None
            job_id = result.job.id
            assert result.job.title == "Senior Python Engineer"
            assert result.job.versions[0].status == "draft"
            assert len(result.job.versions[0].queries) == 10
            assert "unlocked" in result.message
            assert provider.calls == 3
    finally:
        if job_id is not None:
            async with SessionFactory() as session:
                await session.execute(delete(Job).where(Job.id == job_id))
                await session.commit()
