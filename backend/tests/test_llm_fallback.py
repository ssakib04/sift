import asyncio
from types import SimpleNamespace

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


async def test_complete_live_skips_claude() -> None:
    claude = StubProvider(content="from claude")
    gemini = StubProvider(content="from gemini")
    ollama = StubProvider(content="from ollama")
    result = await _manager(claude, gemini, ollama).complete_live("ask one question")

    assert result.content == "from gemini"
    assert result.tier is LLMTier.GEMINI
    assert claude.calls == []
    assert len(gemini.calls) == 1
    assert ollama.calls == []


@pytest.mark.asyncio
async def test_complete_live_does_not_wait_on_another_model() -> None:
    claude = StubProvider(content="from claude")
    gemini = StubProvider(error=RuntimeError("gemini down"))
    ollama = StubProvider(content="from ollama")

    with pytest.raises(LLMFallbackExhaustedError):
        await _manager(claude, gemini, ollama).complete_live("ask one question")

    assert claude.calls == []
    assert ollama.calls == []
    assert len(gemini.calls) == 1


@pytest.mark.asyncio
async def test_complete_local_skips_cloud_tiers() -> None:
    claude = StubProvider(content="from claude")
    gemini = StubProvider(content="from gemini")
    ollama = StubProvider(content="from ollama")
    result = await _manager(claude, gemini, ollama).complete_local("does FastAPI imply Python")

    assert result.content == "from ollama"
    assert result.tier is LLMTier.OLLAMA
    assert result.fallback_used is False
    assert claude.calls == []
    assert gemini.calls == []
    assert len(ollama.calls) == 1


def test_create_fallback_manager_wires_three_tiers() -> None:
    manager = create_fallback_manager(Settings(_env_file=None))
    assert manager.tiers == (LLMTier.CLAUDE, LLMTier.GEMINI, LLMTier.OLLAMA)


@pytest.mark.asyncio
async def test_gemini_retries_overloaded_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class Models:
        def __init__(self) -> None:
            self.calls = 0

        async def generate_content(self, **_kwargs: object) -> SimpleNamespace:
            self.calls += 1
            if self.calls == 1:
                error = type("ServerError", (Exception,), {})("busy")
                error.code = 503
                raise error
            return SimpleNamespace(text="ok")

    models = Models()
    provider = GeminiProvider(api_key="test-gemini", model="gemini-3.8-flash")
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=models))

    async def _no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.core.llm_fallback.asyncio.sleep", _no_wait)
    assert await provider.complete("hello") == "ok"
    assert models.calls == 2


@pytest.mark.asyncio
async def test_brief_reply_sends_a_second_copy_when_the_first_is_slow(monkeypatch: pytest.MonkeyPatch) -> None:
    class Models:
        def __init__(self) -> None:
            self.calls = 0
            self.configs: list[object] = []

        async def generate_content(self, **kwargs: object) -> SimpleNamespace:
            self.calls += 1
            self.configs.append(kwargs.get("config"))
            if self.calls == 1:
                await asyncio.sleep(5)
                return SimpleNamespace(text='{"say": "slow"}')
            return SimpleNamespace(text='{"say": "fast"}')

    models = Models()
    provider = GeminiProvider(api_key="test-gemini", model="gemini-3.5-flash-lite")
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    monkeypatch.setattr("app.core.llm_fallback.BRIEF_HEDGE_SECONDS", 0.01)

    assert await provider.complete_brief("ask", system="be brief") == '{"say": "fast"}'
    assert models.calls == 2
    config = models.configs[0]
    assert getattr(config, "response_mime_type", None) == "application/json"


@pytest.mark.asyncio
async def test_brief_reply_does_not_duplicate_a_fast_call() -> None:
    class Models:
        def __init__(self) -> None:
            self.calls = 0

        async def generate_content(self, **_kwargs: object) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(text='{"say": "hi"}')

    models = Models()
    provider = GeminiProvider(api_key="test-gemini", model="gemini-3.5-flash-lite")
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=models))

    assert await provider.complete_brief("ask") == '{"say": "hi"}'
    assert models.calls == 1


@pytest.mark.asyncio
async def test_brief_reply_gives_up_after_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    class Models:
        async def generate_content(self, **_kwargs: object) -> SimpleNamespace:
            await asyncio.sleep(5)
            return SimpleNamespace(text="late")

    provider = GeminiProvider(api_key="test-gemini", model="gemini-3.5-flash-lite")
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=Models()))
    monkeypatch.setattr("app.core.llm_fallback.BRIEF_HEDGE_SECONDS", 0.01)
    monkeypatch.setattr("app.core.llm_fallback.BRIEF_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(TimeoutError):
        await provider.complete_brief("ask")


@pytest.mark.asyncio
async def test_cloud_providers_reject_missing_api_keys() -> None:
    claude = AnthropicProvider(api_key="", model="claude-sonnet-4-6")
    gemini = GeminiProvider(api_key="", model="gemini-3.1-pro-preview")

    with pytest.raises(LLMProviderError):
        await claude.complete("hello")
    with pytest.raises(LLMProviderError):
        await gemini.complete("hello")
