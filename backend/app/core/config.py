from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ROOT_DIR = _BACKEND_DIR.parent


def env_file_paths() -> tuple[Path, Path]:
    """Root .env feeds Docker Compose. backend/.env feeds a local API process."""
    return (_ROOT_DIR / ".env", _BACKEND_DIR / ".env")


class Settings(BaseSettings):
    """Runtime settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=env_file_paths(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://sift:sift@localhost:5432/sift"
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    anthropic_model: str = "claude-sonnet-4-6"
    gemini_model: str = "gemini-3.1-pro-preview"
    ollama_model: str = "llama3.2"
    policy_storage_dir: str = "data/policies"
    postajob_api_key: str = ""
    postajob_base_url: str = "https://api.postajob.io/v1"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    public_app_url: str = "http://localhost:3000"
    company_name: str = "Sift"
    company_country: str = "Bangladesh"
    embedding_backend: str = "hashing"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    cors_origins: str = "http://localhost:3000"
    mailpit_base_url: str = "http://localhost:8025"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    invite_from_address: str = "jobs@sift.local"
    apply_to_address: str = "careers@sift.local"
    cv_storage_dir: str = "data/cvs"
    mail_poll_seconds: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
