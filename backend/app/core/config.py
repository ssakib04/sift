from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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
    gemini_model: str = "gemini-3.5-flash-lite"
    ollama_model: str = "llama3.2"
    policy_storage_dir: str = "data/policies"
    postajob_api_key: str = ""
    postajob_base_url: str = "https://api.postajob.io/v1"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    mcp_server_url: str = ""
    public_app_url: str = "http://localhost:3000"
    company_name: str = "Sift"
    company_country: str = "Bangladesh"
    embedding_backend: str = "minilm"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    cors_origins: str = "http://localhost:3000"
    mailpit_base_url: str = "http://localhost:8025"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    invite_from_address: str = "jobs@sift.local"
    apply_to_address: str = "fizoadverts@gmail.com"
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    cv_storage_dir: str = "data/cvs"
    mail_poll_seconds: int = 20
    jwt_secret: str = "sift-dev-change-me-before-any-real-interview"
    jwt_ttl_minutes: int = 240
    stun_urls: str = "stun:stun.l.google.com:19302"
    turn_url: str = ""
    turn_username: str = ""
    turn_password: str = ""
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    recruiter_password: str = ""
    api_docs_enabled: bool = False

    @field_validator("imap_password", "smtp_password")
    @classmethod
    def _compact_app_password(cls, value: str) -> str:
        """Gmail shows app passwords in groups of four. IMAP and SMTP reject the spaces."""
        return value.replace(" ", "").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
