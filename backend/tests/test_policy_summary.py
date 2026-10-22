import pytest

from app.core.llm_fallback import LLMResponse, LLMTier
from app.services.policy_ingest import summarize_policy


class LocalModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompts: list[tuple[str, str | None]] = []

    async def complete_local(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        self.prompts.append((prompt, system))
        return LLMResponse(content=self.content, tier=LLMTier.OLLAMA, fallback_used=False)


@pytest.mark.asyncio
async def test_summary_asks_only_the_local_model() -> None:
    model = LocalModel("  Hiring stays fair.\nInterviews follow the checklist.  ")
    summary = await summarize_policy(model, "hiring.docx", "We hire fairly and use a checklist.")

    assert summary == "Hiring stays fair. Interviews follow the checklist."
    assert model.prompts[0][0].startswith("Filename: hiring.docx")
    assert "checklist" in model.prompts[0][0]
    assert model.prompts[0][1] is not None
    assert "two short sentences" in model.prompts[0][1]


@pytest.mark.asyncio
async def test_empty_policy_text_does_not_call_the_model() -> None:
    model = LocalModel("unused")
    summary = await summarize_policy(model, "blank.pdf", "   \n")

    assert summary == "This document has no readable text."
    assert model.prompts == []


@pytest.mark.asyncio
async def test_summary_drops_a_preamble_and_keeps_the_sentences() -> None:
    model = LocalModel("Here is a summary of the policy for a recruiter in two short sentences: Hiring stays fair. Interviews use the checklist.")
    summary = await summarize_policy(model, "hiring.docx", "A rule.")

    assert summary == "Hiring stays fair. Interviews use the checklist."


@pytest.mark.asyncio
async def test_summary_stays_within_the_card_length() -> None:
    model = LocalModel("word " * 200)
    summary = await summarize_policy(model, "long.docx", "A rule.")

    assert len(summary) <= 480
    assert summary.startswith("word")
    assert not summary.endswith(" ")
