import asyncio
import logging
from collections.abc import Sequence
from enum import Enum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

BRIEF_HEDGE_SECONDS = 1.5
BRIEF_TIMEOUT_SECONDS = 5.0


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

    async def complete_local(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_object: bool = False,
    ) -> LLMResponse:
        """Ask only the local Ollama model, without trying Claude or Gemini."""
        tier, provider = self._providers[-1]
        if tier is not LLMTier.OLLAMA:
            raise LLMProviderError("Local model is not configured")
        if json_object and isinstance(provider, OllamaProvider):
            content = await provider.complete_json(prompt, system=system)
        else:
            content = await provider.complete(prompt, system=system)
        return LLMResponse(content=content, tier=LLMTier.OLLAMA, fallback_used=False)

    async def complete_live(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        """Ask Gemini for a short spoken line. A missed reply does not wait on another model."""
        gemini_tier, gemini = self._providers[1]
        brief = getattr(gemini, "complete_brief", None)
        try:
            if brief is not None:
                content = await brief(prompt, system=system)
            else:
                content = await asyncio.wait_for(gemini.complete(prompt, system=system), timeout=4)
        except Exception as exc:
            logger.warning("llm_tier_failed tier=%s error_type=%s", gemini_tier.value, type(exc).__name__)
            raise LLMFallbackExhaustedError([(gemini_tier, type(exc).__name__)]) from exc
        return LLMResponse(content=content, tier=gemini_tier, fallback_used=False)


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


def _retryable_gemini_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(exc, "status_code", None)
    if code in {429, 500, 503}:
        return True
    return type(exc).__name__ == "ServerError"


class GeminiProvider:
    def __init__(self, *, api_key: str, model: str, attempts: int = 3) -> None:
        self._api_key = api_key
        self._model = model
        self._attempts = attempts
        self._client: Any = None

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        return await self._generate(prompt, system=system, max_output_tokens=None, attempts=self._attempts)

    async def complete_brief(self, prompt: str, *, system: str | None = None) -> str:
        """One short JSON reply for a live interview turn.

        A call that is still running after the hedge delay gets a second copy, and the first answer wins.
        """
        loop = asyncio.get_running_loop()
        hedge_at = loop.time() + BRIEF_HEDGE_SECONDS
        deadline = loop.time() + BRIEF_TIMEOUT_SECONDS
        running = {self._brief_task(prompt, system)}
        launched = 1
        failure: BaseException | None = None
        try:
            while running:
                now = loop.time()
                if now >= deadline:
                    raise TimeoutError("Gemini did not reply in time")
                until = deadline if launched > 1 else min(deadline, hedge_at)
                done, running = await asyncio.wait(running, timeout=until - now, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    error = task.exception()
                    if error is None:
                        return task.result()
                    failure = error
                if launched == 1 and (failure is not None or loop.time() >= hedge_at):
                    running.add(self._brief_task(prompt, system))
                    launched += 1
            raise failure if failure is not None else TimeoutError("Gemini did not reply in time")
        finally:
            for task in running:
                task.cancel()

    def _brief_task(self, prompt: str, system: str | None) -> "asyncio.Task[str]":
        return asyncio.create_task(
            self._generate(prompt, system=system, max_output_tokens=200, attempts=1, json_reply=True)
        )

    async def _generate(
        self,
        prompt: str,
        *,
        system: str | None,
        max_output_tokens: int | None,
        attempts: int,
        json_reply: bool = False,
    ) -> str:
        if not self._api_key:
            raise LLMProviderError("Gemini API key is not configured")
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        config = None
        if system or max_output_tokens is not None or json_reply:
            from google.genai import types

            options: dict[str, object] = {}
            if system:
                options["system_instruction"] = system
            if max_output_tokens is not None:
                options["max_output_tokens"] = max_output_tokens
            if json_reply:
                options["response_mime_type"] = "application/json"
                options["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
            config = types.GenerateContentConfig(**options)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= attempts or not _retryable_gemini_error(exc):
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            text = getattr(response, "text", None)
            if not isinstance(text, str) or not text:
                raise LLMProviderError("Gemini returned no text content")
            return text
        if last_error is not None:
            raise last_error
        raise LLMProviderError("Gemini returned no text content")


class OllamaProvider:
    def __init__(self, *, base_url: str, model: str, timeout_seconds: float = 180.0) -> None:
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

    async def complete_json(self, prompt: str, *, system: str | None = None) -> str:
        """A short JSON object from the local model, for a live turn label."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0, "num_predict": 24, "num_ctx": 512, "num_batch": 128},
                },
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
