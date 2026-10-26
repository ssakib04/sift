import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.config import Settings
from app.core.database import SessionFactory
from app.core.llm_fallback import FallbackLLMManager
from app.models.job import Job
from app.schemas.copilot import CopilotMessage, CopilotPlan, CopilotTurnRequest
from app.schemas.job import JobRead, JobVersionRead
from app.schemas.progress import ProgressBoardRead, ProgressCardRead, ProgressColumnRead
from app.services.copilot import (
    PLANNER_SYSTEM,
    NamedJob,
    NamedPerson,
    conversation_transcript,
    explain_from_records,
    explain_pair,
    job_request_from_plan,
    navigate_from_records,
    offer_approve_from_records,
    offer_inbox_turn,
    open_candidate_from_records,
    practice_turn,
    pipeline_from_boards,
    plan_from_model_text,
    rank_from_records,
    resolve_person_query,
    run_copilot_turn,
    select_jobs,
    summarize_jobs,
)
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


def _job(title: str, status: str = "locked") -> NamedJob:
    return NamedJob(id=uuid4(), title=title, status=status)


def _person(
    name: str,
    job: NamedJob,
    *,
    rank: int | None = None,
    aggregate: float | None = None,
    overall: float | None = None,
    label: str = "",
    gap: str = "",
    technical: float | None = None,
    assessed: bool = False,
) -> NamedPerson:
    return NamedPerson(
        id=uuid4(),
        full_name=name,
        job_id=job.id,
        job_title=job.title,
        rank=rank,
        aggregate_score=aggregate,
        overall_score=overall,
        suitability_label=label,
        key_gap=gap,
        technical_dimension=technical,
        experience_dimension=None,
        qualification_dimension=None,
        mcq_score=None,
        interview_qa=None,
        assessed=assessed,
    )


def test_unknown_role_does_not_invent_a_ranking() -> None:
    result = rank_from_records([_job("Data Analyst")], [], "Ghost Role")
    assert result.navigation is None
    assert result.job is None
    assert "Ghost Role" in result.message
    assert "No stored job" in result.message


def test_two_matching_titles_ask_which_role() -> None:
    engineer = _job("Senior Python Engineer")
    analyst = _job("Senior Python Analyst")
    result = rank_from_records([engineer, analyst], [], "Senior Python")
    assert result.navigation is None
    assert "Senior Python Engineer" in result.message
    assert "Senior Python Analyst" in result.message
    assert {chip.prompt for chip in result.chips} == {
        "Rank candidates for Senior Python Engineer",
        "Rank candidates for Senior Python Analyst",
    }


def test_unique_title_ranks_and_opens_the_role() -> None:
    role = _job("Senior Python Engineer")
    priya = _person("Priya Shah", role, rank=2, aggregate=0.4, overall=82.0, label="Strong fit", gap="systems", assessed=True)
    omar = _person("Omar Ali", role, rank=1, aggregate=0.9, overall=71.0, label="Moderate fit", gap="testing", assessed=True)
    result = rank_from_records([role], [omar, priya], "python")
    assert result.navigation is not None
    assert result.navigation.href == f"/candidates?job={role.id}&view=people#people"
    assert result.message.index("Priya Shah") < result.message.index("Omar Ali")
    assert "82.0" in result.message
    assert result.chips[0].kind == "navigate"


def test_explain_cites_stored_scores_for_one_role() -> None:
    role = _job("Senior Python Engineer")
    priya = _person("Priya Shah", role, overall=82.0, label="Strong fit", gap="systems", technical=80.0, assessed=True)
    omar = _person("Omar Ali", role, overall=71.0, label="Moderate fit", gap="testing", technical=60.0, assessed=True)
    text = explain_pair(omar, priya)
    assert "Priya Shah is ahead of Omar Ali" in text
    assert "82.0" in text
    assert "71.0" in text
    assert "systems" in text
    assert "testing" in text
    other = _job("Data Analyst")
    lina = _person("Lina Roy", other, overall=90.0, assessed=True)
    assert "within one role" in explain_pair(priya, lina)


def test_explain_route_opens_the_shared_role() -> None:
    role = _job("Senior Python Engineer")
    priya = _person("Priya Shah", role, overall=82.0, label="Strong fit", gap="systems", assessed=True)
    omar = _person("Omar Ali", role, overall=71.0, label="Moderate fit", gap="testing", assessed=True)
    result = explain_from_records([role], [priya, omar], left_name="Priya", right_name="Omar", job_query=role.title)
    assert result.navigation is not None
    assert result.navigation.href == (
        f"/candidates?job={role.id}&view=compare&left={priya.id}&right={omar.id}#compare"
    )
    assert result.message == "Opening the comparison of Priya Shah and Omar Ali."
    assert result.chips[0].label == "Open comparison"


def test_pipeline_lists_empty_roles_and_stuck_people() -> None:
    empty = ProgressBoardRead(
        job_id=uuid4(),
        job_title="Support Engineer",
        applicant_count=0,
        columns=[ProgressColumnRead(stage=stage, label=stage, cards=[]) for stage in (
            "received",
            "screened",
            "invited",
            "interview",
            "quiz",
            "assessed",
        )],
    )
    invited = ProgressCardRead(candidate_id=uuid4(), full_name="Priya Shah", interview_status="")
    filled_columns = []
    for stage in ("received", "screened", "invited", "interview", "quiz", "assessed"):
        cards = [invited] if stage == "invited" else []
        filled_columns.append(ProgressColumnRead(stage=stage, label=stage, cards=cards))
    active = ProgressBoardRead(
        job_id=uuid4(),
        job_title="Senior Python Engineer",
        applicant_count=1,
        columns=filled_columns,
    )
    result = pipeline_from_boards([active, empty], "summary")
    assert result.navigation is not None
    assert result.navigation.href == "/interviews#interviews"
    assert "Priya Shah on Senior Python Engineer" in result.message
    assert "Support Engineer" in result.message
    empty_only = pipeline_from_boards([active, empty], "empty")
    assert "Priya Shah" not in empty_only.message
    assert "Support Engineer" in empty_only.message


def test_navigate_opens_a_named_place_without_inventing_a_role() -> None:
    home = navigate_from_records([], [], [], place="home", job_query="", candidate_name="")
    assert home.navigation is not None
    assert home.navigation.href == "/#home"
    missed = navigate_from_records([_job("Data Analyst")], [], [], place="job_brief", job_query="Ghost", candidate_name="")
    assert missed.navigation is None
    assert "Ghost" in missed.message


def test_offer_approve_asks_before_posting_a_draft() -> None:
    draft = _job("Backend Engineer", status="draft")
    offered = offer_approve_from_records([draft], "Backend")
    assert offered.navigation is None
    assert offered.chips[0].kind == "confirm"
    assert offered.chips[0].confirm == "approve"
    assert offered.chips[0].job_id == draft.id
    assert offered.chips[0].version_number == 1
    locked = offer_approve_from_records([_job("Backend Engineer", status="locked")], "Backend")
    assert locked.chips[0].kind == "navigate"
    assert "already locked" in locked.message


def test_inbox_check_is_a_confirmation() -> None:
    offered = offer_inbox_turn()
    assert offered.chips[0].confirm == "inbox"
    assert offered.navigation is None
    assert "choose who to invite" in offered.message


def test_practice_turn_carries_the_guest_link_and_the_room() -> None:
    session_id = uuid4()
    result = practice_turn(session_id, "token-1", "recruiter", "http://localhost:3000/invite/abc")
    assert result.practice is not None
    assert result.practice.guest_url.endswith("/invite/abc")
    assert result.navigation is not None
    assert result.navigation.href == f"/interview/{session_id}"


def test_same_name_chips_name_the_role() -> None:
    dancer = _job("Dancer")
    seller = _job("Salesperson")
    people = [_person("Shafat", dancer), _person("Shafat", seller)]
    result = open_candidate_from_records(
        [dancer, seller],
        people,
        name="Shafat",
        job_query="",
        utterance="show me the profile for shafat",
    )
    assert result.navigation is None
    assert result.message.startswith("Which person matches Shafat?")
    assert [chip.label for chip in result.chips] == ["Shafat · Dancer", "Shafat · Salesperson"]
    assert {chip.kind for chip in result.chips} == {"navigate"}
    assert all(chip.href.startswith("/candidates/") for chip in result.chips)


def test_listing_every_shared_name_states_each_role() -> None:
    dancer = _job("Dancer")
    seller = _job("Salesperson")
    result = open_candidate_from_records(
        [dancer, seller],
        [
            _person("Shafat", dancer, rank=1, aggregate=0.4),
            _person("Shafat", seller, rank=2, aggregate=0.2),
        ],
        name="Shafat on Dancer",
        job_query="Dancer",
        utterance="list all the shafat",
    )
    assert "Which person" not in result.message
    assert "2 stored people match Shafat" in result.message
    assert "Dancer" in result.message
    assert "Salesperson" in result.message
    assert {chip.label for chip in result.chips} == {"Shafat · Dancer", "Shafat · Salesperson"}


def test_name_on_role_opens_that_applicant() -> None:
    dancer = _job("Dancer")
    seller = _job("Salesperson")
    people = [_person("Shafat", dancer), _person("Shafat", seller)]
    name, role = resolve_person_query("", "", "Open Shafat on Dancer")
    result = open_candidate_from_records(
        [dancer, seller],
        people,
        name=name,
        job_query=role,
        utterance="Open Shafat on Dancer",
    )
    assert result.navigation is not None
    assert result.navigation.href.endswith("#person")
    assert "Dancer" in result.message
    assert "Salesperson" not in result.message


def test_a_long_chat_keeps_the_latest_command() -> None:
    messages = [
        CopilotMessage(role="assistant" if index % 2 == 0 else "user", content=f"turn {index} " + ("x" * 5000))
        for index in range(30)
    ]
    request = CopilotTurnRequest(messages=messages)
    assert len(request.messages) == 16
    assert request.messages[-1].role == "user"
    assert request.messages[-1].content.startswith("turn 29")
    assert len(request.messages[-1].content) == 4000
    transcript = conversation_transcript(request.messages)
    assert transcript.splitlines()[-1].startswith("user: turn 29")
    assert "…" in transcript


def test_rank_plan_reads_the_job_query() -> None:
    plan = plan_from_model_text(
        '{"action":"rank_job","message":"","job_query":"Senior Python","candidate_name":"","other_name":"","focus":"stuck"}'
    )
    assert isinstance(plan, CopilotPlan)
    assert plan.action == "rank_job"
    assert plan.job_query == "Senior Python"
    assert plan.focus == "stuck"
