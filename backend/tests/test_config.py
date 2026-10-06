import pytest

from app.core.config import Settings

_SETTING_ENV_VARS = (
    "DATABASE_URL",
    "REDIS_URL",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OLLAMA_BASE_URL",
    "ANTHROPIC_MODEL",
    "GEMINI_MODEL",
    "OLLAMA_MODEL",
)


def test_settings_default_to_phase1_models(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://sift:sift@localhost:5432/sift"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.anthropic_model == "claude-3-5-sonnet-20241022"
    assert settings.gemini_model == "gemini-1.5-pro"
    assert settings.ollama_model == "llama3.2"
    assert settings.anthropic_api_key == ""
    assert settings.gemini_api_key == ""


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@postgres:5432/sift")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://user:pass@postgres:5432/sift"
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.anthropic_api_key == "test-anthropic"
    assert settings.gemini_api_key == "test-gemini"
    assert settings.ollama_base_url == "http://ollama:11434"
