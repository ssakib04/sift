import pytest

from app.core.config import Settings, env_file_paths

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


def test_env_files_cover_repo_root_and_backend() -> None:
    root_env, backend_env = env_file_paths()
    assert root_env.name == ".env"
    assert backend_env.name == ".env"
    assert backend_env.parent.name == "backend"
    assert root_env.parent == backend_env.parent.parent


def test_settings_default_to_phase1_models(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://sift:sift@localhost:5432/sift"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.anthropic_model == "claude-sonnet-4-6"
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.ollama_model == "llama3.2"
    assert settings.anthropic_api_key == ""
    assert settings.gemini_api_key == ""
    assert settings.apply_to_address == "fizoadverts@gmail.com"
    assert settings.imap_password == ""


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
