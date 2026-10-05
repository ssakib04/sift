"""Three-tier chat model client and local embedding model for Sift agents."""

from collections.abc import Sequence
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from app.core.config import settings

ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
GEMINI_MODEL = "gemini-1.5-pro"
OLLAMA_MODEL = "llama3.2"
_UNCONFIGURED_KEYS = frozenset({"", "your_anthropic_api_key_here", "not-configured"})


class FallbackChatModel:
    """Anthropic chat model that falls back to Gemini and then local Ollama."""

    def __init__(self, primary: BaseChatModel, fallbacks: Sequence[BaseChatModel]) -> None:
        self.primary = primary
        self.fallbacks = list(fallbacks)
        self.runnable: Runnable[Any, Any] = primary.with_fallbacks(self.fallbacks)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        """Apply the same schema to the primary model and each fallback."""
        structured_primary = self.primary.with_structured_output(schema, **kwargs)
        structured_fallbacks = [
            model.with_structured_output(schema, **kwargs) for model in self.fallbacks
        ]
        return structured_primary.with_fallbacks(structured_fallbacks)

    def invoke(self, model_input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self.runnable.invoke(model_input, config, **kwargs)

    async def ainvoke(self, model_input: Any, config: Any = None, **kwargs: Any) -> Any:
        return await self.runnable.ainvoke(model_input, config, **kwargs)


def get_llm_client(temperature: float | None = None) -> FallbackChatModel:
    """Return Claude, with Gemini and Ollama behind it."""
    resolved_temperature = (
        settings.DEFAULT_LLM_TEMPERATURE if temperature is None else temperature
    )
    primary_llm = ChatAnthropic(
        model=ANTHROPIC_MODEL,
        temperature=resolved_temperature,
        max_retries=0,
        default_request_timeout=8.0,
        **_anthropic_kwargs(),
    )
    gemini_llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=resolved_temperature,
        max_retries=0,
        timeout=8.0,
        google_api_key=_gemini_api_key(),
    )
    ollama_llm = ChatOllama(
        model=OLLAMA_MODEL,
        temperature=resolved_temperature,
        base_url=settings.OLLAMA_BASE_URL,
        client_kwargs={"timeout": 8.0},
        sync_client_kwargs={"timeout": 8.0},
        async_client_kwargs={"timeout": 8.0},
    )
    return FallbackChatModel(primary_llm, [gemini_llm, ollama_llm])


def get_embeddings_model() -> Embeddings:
    """Return the local HuggingFace embedding model named in settings."""
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL_NAME)


def _configured_secret(value: str) -> str | None:
    cleaned = value.strip()
    if cleaned in _UNCONFIGURED_KEYS:
        return None
    return cleaned


def _anthropic_kwargs() -> dict[str, str]:
    key = _configured_secret(settings.ANTHROPIC_API_KEY)
    if key is None:
        return {}
    return {"api_key": key}


def _gemini_api_key() -> str:
    return _configured_secret(settings.GEMINI_API_KEY) or _configured_secret(settings.GOOGLE_API_KEY) or "not-configured"
