from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
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


def test_remote_route_serves_over_plain_http_to_a_lan_client(monkeypatch) -> None:
    app = create_app(settings=Settings())
    lan_ip = "192.168.1.44"
    monkeypatch.setattr(main, "eligible_lan_interface_names", lambda: frozenset({"wi-fi"}))
    monkeypatch.setattr(main, "is_eligible_lan_peer", lambda address: True)
    monkeypatch.setattr(
        main.psutil,
        "net_if_addrs",
        lambda: {
            "Wi-Fi": [
                SimpleNamespace(
                    family=main.socket.AF_INET, address=lan_ip, netmask="255.255.255.0"
                )
            ]
        },
    )

    with TestClient(app, base_url="http://192.168.1.44:8765", client=("192.168.1.87", 50_000)) as client:
        response = client.get("/remote", headers={"host": "192.168.1.44:8765"})

    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_remote_route_serves_public_tunnel_host_from_a_public_peer(monkeypatch) -> None:
    app = create_app(settings=Settings())
    monkeypatch.setenv("PC_TV_PUBLIC_ORIGIN", "https://abc.trycloudflare.com")

    with TestClient(app, base_url="http://127.0.0.1:8765", client=("8.8.8.8", 50_000)) as client:
        response = client.get("/remote", headers={"host": "abc.trycloudflare.com"})

    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_remote_route_rejects_public_peer_without_tunnel_host(monkeypatch) -> None:
    app = create_app(settings=Settings())
    monkeypatch.setenv("PC_TV_PUBLIC_ORIGIN", "https://abc.trycloudflare.com")

    with TestClient(app, base_url="http://127.0.0.1:8765", client=("8.8.8.8", 50_000)) as client:
        response = client.get("/remote", headers={"host": "127.0.0.1:8765"})

    assert response.status_code == 403
    assert response.json()["detail"] == "遠端連線必須來自控制器區網。"

