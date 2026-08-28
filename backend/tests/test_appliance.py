from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.appliance import (
    chrome_launcher_args,
    clear_public_origin,
    ensure_example_configs,
    uvicorn_arguments,
    venv_python,
)


def test_ensure_example_configs_copies_missing_files(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.example.json").write_text("{}", encoding="utf-8")
    (config / "channels.example.json").write_text("[]", encoding="utf-8")
    (config / "news.json").write_text("[]", encoding="utf-8")
    (config / "news.example.json").write_text("[1]", encoding="utf-8")

    created = ensure_example_configs(tmp_path)

    assert {path.name for path in created} == {"settings.json", "channels.json"}
    assert (config / "settings.json").read_text(encoding="utf-8") == "{}"
    assert (config / "news.json").read_text(encoding="utf-8") == "[]"


def test_venv_python_uses_platform_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.appliance.os.name", "nt")
    assert venv_python(tmp_path) == tmp_path / ".venv" / "Scripts" / "python.exe"
    monkeypatch.setattr("app.appliance.os.name", "posix")
    assert venv_python(tmp_path) == tmp_path / ".venv" / "bin" / "python"


def test_chrome_launcher_args_add_linux_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.appliance.os.name", "posix")
    arguments = chrome_launcher_args(
        Path("/usr/bin/google-chrome"),
        "http://127.0.0.1:8765/tv",
        tmp_path / "profile",
    )
    assert arguments[0] == "/usr/bin/google-chrome"
    assert "--start-fullscreen" in arguments
    assert "--password-store=basic" in arguments
    assert "--ozone-platform-hint=auto" in arguments
    assert (tmp_path / "profile").is_dir()


def test_uvicorn_arguments_include_tls_files() -> None:
    arguments = uvicorn_arguments(
        host="0.0.0.0",
        port=8765,
        backend=Path("/tmp/backend"),
        ssl_keyfile=Path("key.pem"),
        ssl_certfile=Path("cert.pem"),
    )
    assert arguments[:4] == ["-m", "uvicorn", "app.main:app", "--host"]
    assert "--ssl-keyfile" in arguments
    assert "key.pem" in arguments
    assert "cert.pem" in arguments


def test_clear_public_origin_drops_stale_tunnel_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    origin = config / "tunnel-origin.txt"
    origin.write_text("https://dead.trycloudflare.com", encoding="utf-8")
    monkeypatch.setenv("PC_TV_PUBLIC_ORIGIN", "https://dead.trycloudflare.com")

    clear_public_origin(tmp_path)

    assert not origin.exists()
    assert "PC_TV_PUBLIC_ORIGIN" not in os.environ
