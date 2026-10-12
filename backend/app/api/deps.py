from app.api.v1.auth import require_recruiter
from app.core.config import Settings, get_settings
from app.core.llm_fallback import FallbackLLMManager, create_fallback_manager
from app.services.embeddings import Embedder, create_embedder
from app.services.postajob import JobPoster, poster_from_settings
from app.services.telegram import TelegramPoster


def get_app_settings() -> Settings:
    return get_settings()


def get_llm() -> FallbackLLMManager:
    return create_fallback_manager()


def get_embedder() -> Embedder:
    return create_embedder()


def get_poster() -> JobPoster:
    settings = get_settings()
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramPoster(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    return poster_from_settings(settings)
