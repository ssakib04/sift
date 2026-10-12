import json

import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.services.interview_analysis import draft_for_empty_transcript, draft_for_transcript


class BoomProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        raise AssertionError("empty transcript must not call the model")


class ScriptedProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del system
        self.calls += 1
        head = prompt.split("Checklist:", 1)[0]
        if "for relevance on a scale" in head:
            return json.dumps({"score": 8, "note": "relevant"})
        if "for technical accuracy on a scale" in head:
            return json.dumps({"score": 7, "note": "accurate"})
        if "for completeness on a scale" in head:
            return json.dumps({"score": 6, "note": "partial"})
        if "for articulation on a scale" in head:
            return json.dumps({"score": 9, "note": "clear"})
        if head.startswith("List requirement gaps"):
            return json.dumps({"gaps": ["Docker"], "summary": "Solid API answers."})
        raise AssertionError(head)


@pytest.mark.asyncio
async def test_empty_transcript_is_scored_without_a_model() -> None:
    draft = await draft_for_transcript(
        FallbackLLMManager(BoomProvider(), BoomProvider(), BoomProvider()),
        ["FastAPI"],
        "   ",
    )
    assert draft == draft_for_empty_transcript()
    assert draft.gaps == ["No interview transcript was captured."]


@pytest.mark.asyncio
async def test_workflow_scores_four_dimensions_then_summarizes() -> None:
    provider = ScriptedProvider()
    draft = await draft_for_transcript(
        FallbackLLMManager(provider, provider, provider),
        ["FastAPI experience", "Docker experience"],
        "candidate [0.0-5.0]: I shipped a FastAPI service.",
    )
    assert provider.calls == 5
    assert draft.relevance == 8
    assert draft.technical_accuracy == 7
    assert draft.completeness == 6
    assert draft.articulation == 9
    assert draft.gaps == ["Docker"]
    assert draft.summary == "Solid API answers."
    assert draft.fallback_used is False
