from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_controller_and_dependency_availability() -> None:
    settings = Settings()
    app = create_app(
        settings=settings,
        capabilities={
            "chrome_available": True,
            "brave_available": True,
            "edge_available": True,
            "mpv_available": False,
        },
        frontend_available=False,
    )

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": app.version,
        "backend": True,
        "frontend": False,
        "chrome_available": True,
        "brave_available": True,
        "edge_available": True,
        "mpv_available": False,
    }
    assert app.version == "0.5.0"
