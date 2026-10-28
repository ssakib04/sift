import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.database import get_session
from app.core.logging import RedactingFormatter, _file_handler
from app.main import app


async def _broken_session() -> None:
    raise RuntimeError("database password=secret host=db.internal")


class _HealthySession:
    async def execute(self, _statement: object) -> object:
        return object()


async def _healthy_session() -> AsyncIterator[_HealthySession]:
    yield _HealthySession()


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _rendered(records: list[logging.LogRecord]) -> str:
    formatter = RedactingFormatter("request_id=%(request_id)s %(message)s")
    return "\n".join(formatter.format(record) for record in records)


def test_log_settings_default_and_reject_unknown_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_DIR", raising=False)

    settings = Settings(_env_file=None)

    assert settings.log_level == "INFO"
    assert settings.log_dir == ""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="verbose")


def test_formatter_redacts_authorization_headers() -> None:
    formatter = RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        name="sift.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer super-secret-token",
        args=(),
        exc_info=None,
    )

    rendered = formatter.format(record)
    query = logging.LogRecord(
        name="sift.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="GET /api/v1/auth/me?token=super-secret-token",
        args=(),
        exc_info=None,
    )

    assert "super-secret-token" not in rendered
    assert "[redacted]" in rendered
    assert "super-secret-token" not in formatter.format(query)
    assert "token=[redacted]" in formatter.format(query)


def test_log_file_redacts_bearer_tokens(tmp_path: Path) -> None:
    directory = tmp_path
    handler = _file_handler(directory)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    record = logging.LogRecord(
        name="sift.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer super-secret-token",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    handler.close()

    text = (directory / "sift.log").read_text(encoding="utf-8")
    assert "super-secret-token" not in text
    assert "[redacted]" in text


def test_request_log_keeps_the_id_and_drops_credentials(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    headers = {"Authorization": "Bearer super-secret-token"}
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me?token=super-secret-token", headers=headers)

    rendered = _rendered(list(caplog.records))
    request_id = response.headers["x-request-id"]
    assert response.status_code == 401
    assert request_id.startswith("req_")
    assert f"request_id={request_id}" in rendered
    assert "request_rejected method=GET path=/api/v1/auth/me status=401" in rendered
    assert "super-secret-token" not in rendered
    assert "authorization" not in rendered.lower()


def test_unhandled_error_returns_the_request_id(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_session] = _broken_session
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/invites/invite-token")

    body = response.json()
    request_id = response.headers["x-request-id"]
    rendered = _rendered(list(caplog.records))
    assert response.status_code == 500
    assert body["detail"]["error_code"] == "INTERNAL_ERROR"
    assert body["detail"]["message"] == "Something went wrong."
    assert body["detail"]["request_id"] == request_id
    assert "secret" not in response.text
    assert "db.internal" not in response.text
    assert f"request_id={request_id}" in rendered
    assert "error_type=RuntimeError" in rendered
    assert "request_failed method=GET path=/api/v1/invites/invite-token status=500" in rendered


def test_health_checks_stay_out_of_the_request_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_session] = _healthy_session
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    request_records = [record for record in caplog.records if record.name == "app.request"]
    rendered = _rendered(request_records)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert request_records == []
    assert "/health" not in rendered
