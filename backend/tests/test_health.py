from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_session
from app.main import app


class FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.rolled_back = False

    async def execute(self, _statement: object) -> object:
        if self.fail:
            raise ConnectionError("database password=secret host=db.internal")
        return object()

    async def rollback(self) -> None:
        self.rolled_back = True


def _override(session: FakeSession):
    async def dependency() -> AsyncIterator[FakeSession]:
        yield session

    return dependency


@pytest.fixture(autouse=True)
def clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_health_reports_database_ok() -> None:
    app.dependency_overrides[get_session] = _override(FakeSession())
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_hides_database_errors() -> None:
    session = FakeSession(fail=True)
    app.dependency_overrides[get_session] = _override(session)
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "database": "unavailable"}
    assert "secret" not in response.text
    assert "db.internal" not in response.text
    assert session.rolled_back is True
