"""Unit tests for the versioned health endpoint."""

from collections.abc import Mapping

from fastapi.testclient import TestClient

from app.main import app


def test_get_health_returns_ok_payload() -> None:
    """GET /api/v1/health returns HTTP 200 and the expected liveness fields."""
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload: Mapping[str, object] = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "sift-api"
    assert payload["version"] == "0.1.0"
