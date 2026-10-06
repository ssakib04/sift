import logging
from collections.abc import Sequence
from enum import Enum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMTier(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class LLMResponse(BaseModel):
    content: str
    tier: LLMTier
    fallback_used: bool


class LLMProviderError(RuntimeError):
    """A single provider failed before the next tier is tried."""


class LLMFallbackExhaustedError(RuntimeError):
    """Claude, Gemini, and Ollama all failed for one completion."""

    def __init__(self, failures: Sequence[tuple[LLMTier, str]]) -> None:
        self.failures = list(failures)
        tiers = ", ".join(tier.value for tier, _error_type in self.failures)
        super().__init__(f"All LLM tiers failed: {tiers}")


class LLMProvider(Protocol):
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Return the model text for a prompt."""


class FallbackLLMManager:
    """Route every completion through Claude, then Gemini, then Ollama."""

    def __init__(
        self,
        claude: LLMProvider,
        gemini: LLMProvider,
        ollama: LLMProvider,
    ) -> None:
        self._providers: tuple[tuple[LLMTier, LLMProvider], ...] = (
            (LLMTier.CLAUDE, claude),
            (LLMTier.GEMINI, gemini),
            (LLMTier.OLLAMA, ollama),
        )

    @property
    def tiers(self) -> tuple[LLMTier, ...]:
        return tuple(tier for tier, _provider in self._providers)

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        failures: list[tuple[LLMTier, str]] = []
        for index, (tier, provider) in enumerate(self._providers):
            try:
                content = await provider.complete(prompt, system=system)
            except Exception as exc:
                failures.append((tier, type(exc).__name__))
                logger.warning(
                    "llm_tier_failed tier=%s error_type=%s",
                    tier.value,
                    type(exc).__name__,
                )
                continue
            if index > 0:
                skipped = ",".join(failed_tier.value for failed_tier, _error_type in failures)
                logger.warning("llm_fallback_used tier=%s skipped=%s", tier.value, skipped)
            return LLMResponse(content=content, tier=tier, fallback_used=index > 0)
        raise LLMFallbackExhaustedError(failures)


class AnthropicProvider:
    def __init__(self, *, api_key: str, model: str, max_tokens: int = 4096) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._client: Any = None

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        if not self._api_key:
            raise LLMProviderError("Anthropic API key is not configured")
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        kwargs: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        message = await self._client.messages.create(**kwargs)
        parts: list[str] = []
        for block in message.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        if not parts:
            raise LLMProviderError("Anthropic returned no text content")
        return "".join(parts)


class GeminiProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        if not self._api_key:
            raise LLMProviderError("Gemini API key is not configured")
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        config = None
        if system:
            from google.genai import types

            config = types.GenerateContentConfig(system_instruction=system)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text:
            raise LLMProviderError("Gemini returned no text content")
        return text


class OllamaProvider:
    def __init__(self, *, base_url: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={"model": self._model, "messages": messages, "stream": False},
            )
            response.raise_for_status()
            payload = response.json()
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content:
            raise LLMProviderError("Ollama returned no text content")
        return content


def create_fallback_manager(settings: Settings | None = None) -> FallbackLLMManager:
    """Build the only supported LLM entry point from application settings."""
    resolved = settings or get_settings()
    return FallbackLLMManager(
        claude=AnthropicProvider(api_key=resolved.anthropic_api_key, model=resolved.anthropic_model),
        gemini=GeminiProvider(api_key=resolved.gemini_api_key, model=resolved.gemini_model),
        ollama=OllamaProvider(base_url=resolved.ollama_base_url, model=resolved.ollama_model),
    )
