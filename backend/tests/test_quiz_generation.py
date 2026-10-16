import json

import pytest

from app.core.llm_fallback import FallbackLLMManager, LLMTier
from app.services.quiz_rules import QuizGenerationError
from app.services.quiz_service import generate_quiz
from tests.checklist_factory import sample_queries


class ScriptedProvider:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del system
        self.prompts.append(prompt)
        return self.answer


class BrokenProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        raise RuntimeError("down")


def _checklist() -> list[dict[str, str]]:
    return [
        {
            "query_id": str(item["query_id"]),
            "question": str(item["question"]),
            "dimension": str(item["dimension"]),
            "requirement_type": str(item["requirement_type"]),
            "scoring_rubric": str(item["scoring_rubric"]),
        }
        for item in sample_queries()
    ]


def _payload() -> str:
    questions = [
        {
            "question_id": f"Q{index}",
            "query_id": f"Q{index}",
            "prompt": f"Which choice shows production skill number {index}?",
            "options": ["Alpha", "Beta", "Gamma", "Delta"],
            "correct_index": 1,
            "explanation": f"Beta matches the rubric for criterion {index}.",
        }
        for index in range(1, 11)
    ]
    return json.dumps({"questions": questions})


@pytest.mark.asyncio
async def test_generation_uses_the_fallback_manager_and_starts_ten_questions() -> None:
    provider = ScriptedProvider(_payload())
    llm = FallbackLLMManager(provider, provider, provider)
    state, tier, fallback_used = await generate_quiz(
        llm,
        job_title="Senior Python Engineer",
        checklist=_checklist(),
        cv_text="Built FastAPI services for hiring workflows.",
    )
    assert tier == LLMTier.CLAUDE.value
    assert fallback_used is False
    assert [question.question_id for question in state.paper.questions] == [f"Q{index}" for index in range(1, 11)]
    assert state.score is None
    assert "Senior Python Engineer" in provider.prompts[0]
    assert "Built FastAPI services" in provider.prompts[0]
    assert provider.prompts[0].count("Q10") >= 1


@pytest.mark.asyncio
async def test_generation_falls_through_to_the_next_tier() -> None:
    provider = ScriptedProvider(_payload())
    llm = FallbackLLMManager(BrokenProvider(), provider, provider)
    _state, tier, fallback_used = await generate_quiz(
        llm,
        job_title="Senior Python Engineer",
        checklist=_checklist(),
        cv_text="",
    )
    assert tier == LLMTier.GEMINI.value
    assert fallback_used is True


@pytest.mark.asyncio
async def test_generation_rejects_a_short_quiz() -> None:
    provider = ScriptedProvider(json.dumps({"questions": []}))
    llm = FallbackLLMManager(provider, provider, provider)
    with pytest.raises(QuizGenerationError):
        await generate_quiz(
            llm,
            job_title="Senior Python Engineer",
            checklist=_checklist(),
            cv_text="No CV text is available.",
        )
