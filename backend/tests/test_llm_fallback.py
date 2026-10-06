import pytest

from app.core.config import Settings
from app.core.llm_fallback import (
    AnthropicProvider,
    FallbackLLMManager,
    GeminiProvider,
    LLMFallbackExhaustedError,
    LLMProviderError,
    LLMTier,
    create_fallback_manager,
)


class StubProvider:
    def __init__(self, *, content: str | None = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        if self._error is not None:
            raise self._error
        if self._content is None:
            raise RuntimeError("stub provider has no content")
        return self._content


def _manager(
    claude: StubProvider,
    gemini: StubProvider,
    ollama: StubProvider,
) -> FallbackLLMManager:
    return FallbackLLMManager(claude=claude, gemini=gemini, ollama=ollama)


@pytest.mark.asyncio
async def test_primary_claude_succeeds_without_fallback() -> None:
    claude = StubProvider(content="from claude")
    gemini = StubProvider(content="from gemini")
    ollama = StubProvider(content="from ollama")
    result = await _manager(claude, gemini, ollama).complete("draft a job description", system="be concise")

    assert result.content == "from claude"
    assert result.tier is LLMTier.CLAUDE
    assert result.fallback_used is False
    assert claude.calls == [("draft a job description", "be concise")]
    assert gemini.calls == []
    assert ollama.calls == []


@pytest.mark.asyncio
async def test_claude_failure_uses_gemini() -> None:
    claude = StubProvider(error=LLMProviderError("claude unavailable"))
    gemini = StubProvider(content="from gemini")
    ollama = StubProvider(content="from ollama")
    result = await _manager(claude, gemini, ollama).complete("score this cv")

    assert result.content == "from gemini"
    assert result.tier is LLMTier.GEMINI
    assert result.fallback_used is True
    assert len(claude.calls) == 1
    assert len(gemini.calls) == 1
    assert ollama.calls == []


@pytest.mark.asyncio
async def test_claude_and_gemini_failure_uses_ollama() -> None:
    claude = StubProvider(error=RuntimeError("claude down"))
    gemini = StubProvider(error=RuntimeError("gemini down"))
    ollama = StubProvider(content="from ollama")
    result = await _manager(claude, gemini, ollama).complete("summarize the interview")

    assert result.content == "from ollama"
    assert result.tier is LLMTier.OLLAMA
    assert result.fallback_used is True
    assert len(ollama.calls) == 1


@pytest.mark.asyncio
async def test_all_tiers_fail_raises_single_error() -> None:
    claude = StubProvider(error=RuntimeError("claude down"))
    gemini = StubProvider(error=RuntimeError("gemini down"))
    ollama = StubProvider(error=RuntimeError("ollama down"))

    with pytest.raises(LLMFallbackExhaustedError) as caught:
        await _manager(claude, gemini, ollama).complete("hello")

    assert [tier for tier, _error_type in caught.value.failures] == [
        LLMTier.CLAUDE,
        LLMTier.GEMINI,
        LLMTier.OLLAMA,
    ]
    assert len(claude.calls) == len(gemini.calls) == len(ollama.calls) == 1


def test_create_fallback_manager_wires_three_tiers() -> None:
    manager = create_fallback_manager(Settings(_env_file=None))
    assert manager.tiers == (LLMTier.CLAUDE, LLMTier.GEMINI, LLMTier.OLLAMA)


@pytest.mark.asyncio
async def test_cloud_providers_reject_missing_api_keys() -> None:
    claude = AnthropicProvider(api_key="", model="claude-3-5-sonnet-20241022")
    gemini = GeminiProvider(api_key="", model="gemini-1.5-pro")

    with pytest.raises(LLMProviderError):
        await claude.complete("hello")
    with pytest.raises(LLMProviderError):
        await gemini.complete("hello")
