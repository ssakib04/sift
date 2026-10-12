import json

import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.services.interview_copilot import copilot_from_transcript, copilot_without_speech


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
        assert "FastAPI" in prompt
        return json.dumps(
            {
                "explored": ["FastAPI"],
                "gaps": ["Docker"],
                "suggested_question": "How did you ship the API?",
            }
        )


@pytest.mark.asyncio
async def test_copilot_lists_checklist_gaps_before_anyone_speaks() -> None:
    draft = await copilot_from_transcript(
        FallbackLLMManager(BoomProvider(), BoomProvider(), BoomProvider()),
        ["FastAPI experience", "Docker experience"],
        "",
    )
    assert draft == copilot_without_speech(["FastAPI experience", "Docker experience"])
    assert draft.suggested_question == "FastAPI experience"


@pytest.mark.asyncio
async def test_copilot_reads_the_transcript_through_the_fallback_manager() -> None:
    provider = ScriptedProvider()
    draft = await copilot_from_transcript(
        FallbackLLMManager(provider, provider, provider),
        ["FastAPI experience"],
        "candidate [0.0-5.0]: I shipped FastAPI.",
    )
    assert provider.calls == 1
    assert draft.explored == ["FastAPI"]
    assert draft.gaps == ["Docker"]
    assert draft.suggested_question == "How did you ship the API?"
