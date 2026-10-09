from fastapi.testclient import TestClient

from date_romania import __version__
from date_romania.api import main


def test_health_reports_database_state(monkeypatch):
    monkeypatch.setattr(main, "database_ok", lambda: True)
    response = TestClient(main.app).get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": __version__}


def test_health_degraded_without_database(monkeypatch):
    monkeypatch.setattr(main, "database_ok", lambda: False)
    response = TestClient(main.app).get("/v1/health")
    assert response.json()["status"] == "degraded"


def test_openapi_schema_is_published():
    assert TestClient(main.app).get("/openapi.json").status_code == 200
