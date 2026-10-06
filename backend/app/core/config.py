from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://sift:sift@localhost:5432/sift"
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    gemini_model: str = "gemini-1.5-pro"
    ollama_model: str = "llama3.2"


@lru_cache
def get_settings() -> Settings:
    return Settings()
