"""Runtime settings loaded from the environment."""

from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application configuration sourced from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Sift"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "sift"
    POSTGRES_PASSWORD: str = "sift_secret"
    POSTGRES_DB: str = "sift_db"
    POSTGRES_HOST_PORT: int = 5433
    DATABASE_URL: str = "postgresql://sift:sift_secret@localhost:5433/sift_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = ""
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    DEFAULT_LLM_TEMPERATURE: float = 0.0
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, (list, tuple)):
            return [str(origin).strip() for origin in value if str(origin).strip()]
        raise ValueError("CORS_ORIGINS must be a comma-separated string or a list of origins")

    @model_validator(mode="after")
    def _synchronize_google_keys(self) -> "Settings":
        resolved = self.GEMINI_API_KEY.strip() or self.GOOGLE_API_KEY.strip()
        self.GEMINI_API_KEY = resolved
        self.GOOGLE_API_KEY = resolved
        return self


settings = Settings()
