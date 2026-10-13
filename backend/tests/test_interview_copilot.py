import json

import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.services.interview_copilot import (
    ask_copilot,
    copilot_from_transcript,
    copilot_without_speech,
    cv_profile_text,
    normalize_copilot_ask,
)
from app.services.interview_rules import InterviewError


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
    assert draft == copilot_without_speech(
        ["FastAPI experience", "Docker experience"],
        profile_available=False,
    )
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
    assert draft.profile_available is False


def test_cv_profile_keeps_the_name_and_drops_a_blank_cv() -> None:
    assert cv_profile_text("Ada Lovelace", "   ") == ""
    text = cv_profile_text("Ada Lovelace", "Skills: pgvector " + ("x" * 7000))
    assert text.startswith("Ada Lovelace\n")
    assert "pgvector" in text
    assert len(text) < 6200


def test_blank_copilot_ask_is_rejected() -> None:
    with pytest.raises(InterviewError) as denied:
        normalize_copilot_ask("   ")
    assert denied.value.code == "COPILOT_QUESTION_REQUIRED"


class AskingProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.prompt = ""

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del system
        self.prompt = prompt
        return json.dumps(self.payload)


@pytest.mark.asyncio
async def test_ask_uses_cv_skills_and_what_was_already_said() -> None:
    provider = AskingProvider(
        {"reply": "Probe the untested claim.", "questions": ["How did you use pgvector?"]}
    )
    answer = await ask_copilot(
        FallbackLLMManager(provider, provider, provider),
        ["API design"],
        "recruiter [0.0-4.0]: Tell me about your APIs.",
        cv_profile_text("Ada Lovelace", "Skills include pgvector and FastAPI."),
        "What should I ask next?",
    )
    assert "pgvector" in provider.prompt
    assert "Tell me about your APIs." in provider.prompt
    assert "What should I ask next?" in provider.prompt
    assert answer.profile_available is True
    assert answer.questions == ["How did you use pgvector?"]


@pytest.mark.asyncio
async def test_ask_says_when_no_cv_is_stored() -> None:
    provider = AskingProvider({"reply": "Ask about the checklist.", "questions": ["How do you design APIs?"]})
    answer = await ask_copilot(
        FallbackLLMManager(provider, provider, provider),
        ["API design"],
        "",
        "",
        "Give me a question",
    )
    assert "No CV is stored for this person." in provider.prompt
    assert answer.profile_available is False
    assert answer.reply.startswith("No CV is stored for this person.")
    assert answer.questions == ["How do you design APIs?"]
