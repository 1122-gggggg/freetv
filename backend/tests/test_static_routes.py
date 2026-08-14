from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_tv_and_remote_routes_serve_the_production_single_page_application() -> None:
    app = create_app(settings=Settings())

    with TestClient(
        app, base_url="https://127.0.0.1:8765", client=("127.0.0.1", 50_000)
    ) as client:
        tv = client.get("/tv")
        remote = client.get("/remote", headers={"host": "127.0.0.1:8765"})

    assert tv.status_code == 200
    assert remote.status_code == 200
    assert 'id="root"' in tv.text
    assert 'id="root"' in remote.text
    assert tv.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert remote.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert tv.headers["x-frame-options"] == "DENY"
    assert remote.headers["x-frame-options"] == "DENY"


def test_remote_route_rejects_an_untrusted_host() -> None:
    app = create_app(settings=Settings())

    with TestClient(
        app, base_url="https://127.0.0.1:8765", client=("127.0.0.1", 50_000)
    ) as client:
        response = client.get("/remote", headers={"host": "attacker.example:8765"})

    assert response.status_code == 403
