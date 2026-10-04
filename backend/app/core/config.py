"""Runtime settings loaded from the environment."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application configuration sourced from environment variables."""

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
    ANTHROPIC_API_KEY: str = "your_anthropic_api_key_here"


settings = Settings()
