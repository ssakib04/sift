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
    face_backend: str = "insightface"
    face_model: str = "buffalo_l"
    face_model_dir: str = ""
    face_confirm_threshold: float = 0.42
    face_possible_threshold: float = 0.32
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
    ai_interviewer_enabled: bool = True
    whisper_model: str = "base.en"
    whisper_device: str = "auto"
    whisper_cpu_threads: int = 4
    speech_model_dir: str = "data/speech"
    piper_voice: str = "en_GB-cori-medium"
    speech_voice_engine: str = "kokoro"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.08
    groq_api_key: str = ""
    groq_stt_model: str = "whisper-large-v3-turbo"
    groq_tts_model: str = "canopylabs/orpheus-v1-english"
    groq_tts_voice: str = "autumn"
    recruiter_password: str = ""
    api_docs_enabled: bool = False
    interview_duration_minutes: int = 45
    interview_day_start_hour: int = 10
    interview_day_end_hour: int = 17
    interview_lead_minutes: int = 120
    interview_timezone: str = "Asia/Dhaka"
    interview_weekdays: str = "0,1,2,3,4"
    recruiter_calendar_email: str = ""
    google_calendar_client_id: str = ""
    google_calendar_client_secret: str = ""
    google_calendar_refresh_token: str = ""
    google_calendar_id: str = "primary"
    log_level: str = "INFO"
    log_dir: str = ""

    @field_validator("imap_password", "smtp_password")
    @classmethod
    def _compact_app_password(cls, value: str) -> str:
        """Gmail shows app passwords in groups of four. IMAP and SMTP reject the spaces."""
        return value.replace(" ", "").strip()

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        name = value.strip().upper()
        if name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return name

    @field_validator("log_dir")
    @classmethod
    def _strip_log_dir(cls, value: str) -> str:
        return value.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
