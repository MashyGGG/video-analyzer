import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.parametrize(
    "database,redis,expected",
    [(True, True, 200), (False, True, 503), (True, False, 503), (False, False, 503)],
)
def test_readiness_tracks_real_dependencies_and_not_models(database, redis, expected):
    client = TestClient(create_app(lambda: {"database": database, "redis": redis}))
    assert client.get("/api/v1/health/live").status_code == 200
    response = client.get("/api/v1/health/ready")
    assert response.status_code == expected
    assert response.json()["dependencies"] == {"database": database, "redis": redis}
    assert response.json()["models"] == "not_configured"
    assert "password" not in response.text.lower()


def test_dependency_exception_is_not_disclosed():
    def broken():
        raise RuntimeError("redis://:sensitive-password@redis:6379")

    client = TestClient(create_app(broken))
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "sensitive" not in response.text


def test_acquisition_contract_and_health_need_no_model_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unused-fake-value")
    client = TestClient(create_app(lambda: {"database": True, "redis": True}))
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "0.1.0"
    assert "post" in spec["paths"]["/api/v1/assets/upload"]
    assert client.post("/api/v1/assets/upload").status_code == 401
    assert client.get("/api/v1/health/live").status_code == 200
