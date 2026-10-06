import pytest

from app.core.llm_fallback import FallbackLLMManager, LLMResponse, LLMTier
from app.graphs.job_creation_graph import JobGraphError, build_job_creation_graph, state_from_request
from app.schemas.job import JobCreateRequest
from tests.checklist_factory import sample_queries


class ScriptedProvider:
    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        answer = self._answers[self.calls]
        self.calls += 1
        return answer


class StaticRetriever:
    async def search(self, query: str, limit: int = 5) -> list[str]:
        del query, limit
        return ["Remote work requires manager approval."]


def _request() -> JobCreateRequest:
    return JobCreateRequest(
        title="Senior Python Engineer",
        seniority="Senior",
        required_skills=["Python", "FastAPI"],
        preferred_skills=["LangGraph"],
        qualifications="Bachelor in computer science",
        minimum_years=4,
    )


@pytest.mark.asyncio
async def test_workflow_returns_description_and_ten_queries() -> None:
    import json

    description = (
        "We are hiring a Senior Python Engineer to build policy-compliant APIs. "
        "Remote work requires manager approval. The role needs production FastAPI experience."
    )
    provider = ScriptedProvider(
        [
            json.dumps({"description": description}),
            json.dumps({"queries": sample_queries()}),
        ]
    )
    llm = FallbackLLMManager(provider, provider, provider)
    run = build_job_creation_graph(llm, StaticRetriever())
    result = await run(state_from_request(_request()))

    assert result["description"] == description
    assert [query.query_id for query in result["queries"]] == [f"Q{index}" for index in range(1, 11)]
    assert result["policy_excerpts"] == ["Remote work requires manager approval."]
    assert result["llm_tier"] == LLMTier.CLAUDE.value
    assert abs(sum(query.weight for query in result["queries"]) - 1) < 0.001


@pytest.mark.asyncio
async def test_workflow_accepts_rubric_objects_as_text() -> None:
    import json

    description = "A" * 120
    queries = sample_queries()
    for query in queries:
        query["scoring_rubric"] = {"0": "No evidence of the skill.", "1": "Used in production."}
    provider = ScriptedProvider(
        [
            json.dumps({"description": description}),
            json.dumps({"queries": queries}),
        ]
    )
    llm = FallbackLLMManager(provider, provider, provider)
    run = build_job_creation_graph(llm, StaticRetriever())
    result = await run(state_from_request(_request()))

    assert result["queries"][0].scoring_rubric == "No evidence of the skill. Used in production."


@pytest.mark.asyncio
async def test_workflow_rejects_incomplete_checklist() -> None:
    import json

    description = "A" * 120
    provider = ScriptedProvider(
        [
            json.dumps({"description": description}),
            json.dumps({"queries": sample_queries()[:9]}),
        ]
    )
    llm = FallbackLLMManager(provider, provider, provider)
    run = build_job_creation_graph(llm, StaticRetriever())
    with pytest.raises(JobGraphError):
        await run(state_from_request(_request()))


def test_scripted_response_type_matches_manager() -> None:
    assert LLMResponse(content="ok", tier=LLMTier.CLAUDE, fallback_used=False).fallback_used is False
