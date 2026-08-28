from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from app.config import load_settings, project_root, resolve_application_paths

MINIMUM_PYTHON = (3, 11)
CONTROLLER_MODULE = "app.main:app"


def venv_python(root: Path | None = None) -> Path:
    base = root or project_root()
    if os.name == "nt":
        return base / ".venv" / "Scripts" / "python.exe"
    return base / ".venv" / "bin" / "python"


def venv_directory(root: Path | None = None) -> Path:
    return (root or project_root()) / ".venv"


def ensure_example_configs(root: Path | None = None) -> list[Path]:
    base = root or project_root()
    created: list[Path] = []
    for name in ("settings", "channels", "news"):
        destination = base / "config" / f"{name}.json"
        source = base / "config" / f"{name}.example.json"
        if destination.exists() or not source.exists():
            continue
        destination.write_bytes(source.read_bytes())
        created.append(destination)
    return created


def public_origin_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "config" / "tunnel-origin.txt"


def clear_public_origin(root: Path | None = None) -> None:
    origin = public_origin_path(root)
    if origin.exists():
        origin.unlink()
    os.environ.pop("PC_TV_PUBLIC_ORIGIN", None)


def frontend_index(root: Path | None = None) -> Path:
    return (root or project_root()) / "frontend" / "dist" / "index.html"


def port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((host, port)) == 0


def chrome_launcher_args(executable: Path, url: str, user_data_dir: Path) -> list[str]:
    user_data_dir.mkdir(parents=True, exist_ok=True)
    arguments = [
        str(executable),
        "--start-fullscreen",
        url,
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
        "--disable-session-crashed-bubble",
        "--noerrdialogs",
        "--disable-extensions",
        "--disable-sync",
        f"--user-data-dir={user_data_dir}",
    ]
    if os.name != "nt":
        arguments.extend(["--password-store=basic", "--ozone-platform-hint=auto"])
    return arguments


def uvicorn_arguments(
    *,
    host: str,
    port: int,
    backend: Path,
    ssl_keyfile: Path | None = None,
    ssl_certfile: Path | None = None,
) -> list[str]:
    arguments = [
        "-m",
        "uvicorn",
        CONTROLLER_MODULE,
        "--host",
        host,
        "--port",
        str(port),
        "--app-dir",
        str(backend),
        "--ws",
        "websockets-sansio",
        "--limit-concurrency",
        "64",
        "--backlog",
        "64",
        "--ws-max-size",
        "65536",
        "--ws-max-queue",
        "16",
        "--timeout-keep-alive",
        "10",
    ]
    if ssl_keyfile is not None and ssl_certfile is not None:
        arguments.extend(["--ssl-keyfile", str(ssl_keyfile), "--ssl-certfile", str(ssl_certfile)])
    return arguments


def _run(arguments: Sequence[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(list(arguments), cwd=cwd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{arguments[0]} failed with exit code {completed.returncode}.")


def _require_python_version() -> None:
    if sys.version_info < MINIMUM_PYTHON:
        raise RuntimeError(
            f"FreeTV 需要 Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} 或更新版本。"
        )


def setup_appliance(root: Path | None = None) -> None:
    _require_python_version()
    base = root or project_root()
    python = venv_python(base)
    env_dir = venv_directory(base)
    if not python.is_file():
        print(f"Creating virtual environment at {env_dir}...")
        _run([sys.executable, "-m", "venv", str(env_dir)])
    print("Installing backend dependencies...")
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(python), "-m", "pip", "install", "-r", str(base / "backend" / "requirements.txt")])
    print("Installing AdBlock extensions...")
    _run(
        [
            str(python),
            "-m",
            "app.applications.adblock",
            "--directory",
            str(base / "vendor" / "adblock"),
            "--youtube-directory",
            str(base / "vendor" / "adblock-youtube"),
        ],
        cwd=base / "backend",
    )
    if os.name == "nt":
        _run([str(python), "-m", "app.applications.chrome_policy"], cwd=base / "backend")
    dist = frontend_index(base)
    if dist.is_file():
        print("Frontend build found at frontend/dist; skipping npm install and build.")
    else:
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "找不到 frontend/dist。請使用 GitHub Release zip，或安裝 Node.js LTS 後重跑 setup。"
            )
        print("Building frontend...")
        _run([npm, "ci"], cwd=base / "frontend")
        _run([npm, "run", "build"], cwd=base / "frontend")
        if not dist.is_file():
            raise RuntimeError("Frontend build did not produce frontend/dist/index.html.")
    created = ensure_example_configs(base)
    for path in created:
        print(f"Created {path.relative_to(base)} from example.")
    print_doctor(base)
    print("Setup complete. Start with: python freetv.py start")


def print_doctor(root: Path | None = None) -> None:
    base = root or project_root()
    settings = load_settings(base / "config" / "settings.json")
    paths = resolve_application_paths(settings)
    python = venv_python(base)
    print(f"OS: {sys.platform} ({os.name})")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Venv: {'ok' if python.is_file() else 'missing'} ({python})")
    print(f"Frontend: {'ok' if frontend_index(base).is_file() else 'missing'}")
    for name in ("chrome", "brave", "edge", "mpv"):
        found = paths.get(name)
        print(f"{name}: {found if found else 'not found'}")
    cloudflared = shutil.which("cloudflared")
    print(f"cloudflared: {cloudflared if cloudflared else 'not found'}")
    print(f"xdotool: {shutil.which('xdotool') or 'not found'}")


def _wait_json(url: str, *, timeout: float, verify: bool) -> dict[str, object]:
    import httpx

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0, verify=verify)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
            time.sleep(0.3)
    raise RuntimeError(f"Controller did not become ready at {url}.") from last_error


def start_appliance(
    *,
    root: Path | None = None,
    no_browser: bool = False,
    no_tunnel: bool = False,
    supervise: bool = False,
) -> int:
    _require_python_version()
    base = root or project_root()
    python = venv_python(base)
    if not python.is_file():
        raise RuntimeError("找不到虛擬環境。請先執行 python freetv.py setup。")
    if not frontend_index(base).is_file():
        raise RuntimeError("找不到 frontend/dist。請先執行 python freetv.py setup。")
    ensure_example_configs(base)
    clear_public_origin(base)
    settings = load_settings(base / "config" / "settings.json")
    if settings.server.host != "0.0.0.0":
        raise RuntimeError("server.host 必須是 0.0.0.0，遙控器與 loopback 政策才會分開。")
    backend = base / "backend"
    ssl_keyfile: Path | None = None
    ssl_certfile: Path | None = None
    scheme = "http"
    verify_health = True
    if settings.server.transport == "https":
        from app.security.tls import (
            certificate_fingerprint,
            ensure_tls_materials,
            wait_for_lan_interface_addresses,
        )

        materials = ensure_tls_materials(
            base / "config" / "tls",
            wait_for_lan_interface_addresses(30),
        )
        ssl_keyfile = materials.private_key
        ssl_certfile = materials.certificate
        scheme = "https"
        verify_health = False
        print(f"Local TLS CA: {materials.ca_certificate}")
        print(f"CA SHA-256: {certificate_fingerprint(materials.ca_certificate)}")

    process: subprocess.Popen[bytes] | None = None
    if not port_is_listening(settings.server.port):
        print("Starting PC TV Controller...")
        process = subprocess.Popen(
            [
                str(python),
                *uvicorn_arguments(
                    host=settings.server.host,
                    port=settings.server.port,
                    backend=backend,
                    ssl_keyfile=ssl_keyfile,
                    ssl_certfile=ssl_certfile,
                ),
            ],
            cwd=backend,
        )
        print(f"Backend process started: {process.pid}")

    health_url = f"{scheme}://127.0.0.1:{settings.server.port}/api/health"
    pairing_url = f"{scheme}://127.0.0.1:{settings.server.port}/api/pairing"
    health = _wait_json(health_url, timeout=30, verify=verify_health)
    if (
        health.get("status") != "ok"
        or health.get("backend") is not True
        or health.get("frontend") is not True
    ):
        raise RuntimeError(f"Controller did not become fully healthy at {health_url}.")
    pairing = _wait_json(pairing_url, timeout=15, verify=verify_health)

    origin_file = base / "config" / "tunnel-origin.txt"
    if not no_tunnel:
        cloudflared = shutil.which("cloudflared")
        if cloudflared is None:
            print("cloudflared 未安裝。區網外遙控不可用。")
        else:
            public_origin = _start_cloudflare_tunnel(
                cloudflared,
                port=settings.server.port,
                log_directory=base / "config",
            )
            if public_origin:
                origin_file.write_text(public_origin, encoding="utf-8")
                os.environ["PC_TV_PUBLIC_ORIGIN"] = public_origin
                pairing = _wait_json(pairing_url, timeout=15, verify=verify_health)
                print(f"Cloudflare Tunnel: {public_origin}")
            else:
                print("cloudflared 30 秒內沒有印出 trycloudflare.com URL。")

    local_url = f"{scheme}://127.0.0.1:{settings.server.port}/tv"
    remote_url = str(
        pairing.get("remote_url") or f"{scheme}://<PC-LAN-IP>:{settings.server.port}/remote"
    )
    print(f"TV Launcher: {local_url}")
    print(f"Phone Remote: {remote_url}")
    print(f"Health: {health_url}")

    if not no_browser:
        _open_tv_launcher(base, local_url)

    if supervise:
        if process is None:
            raise RuntimeError("無法監督一個不是由這次啟動建立的控制器。")
        return_code = process.wait()
        raise RuntimeError(f"PC TV Controller process {process.pid} exited with {return_code}.")
    return 0


def _start_cloudflare_tunnel(cloudflared: str, *, port: int, log_directory: Path) -> str | None:
    from app.main import parse_cloudflared_origin

    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "cloudflared.log"
    out_path = log_directory / "cloudflared.out.log"
    for path in (log_path, out_path):
        if path.exists():
            path.unlink()
    with log_path.open("wb") as error_log, out_path.open("wb") as output_log:
        subprocess.Popen(
            [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stdout=output_log,
            stderr=error_log,
        )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        text = ""
        if log_path.exists():
            text += log_path.read_text(encoding="utf-8", errors="replace")
        if out_path.exists():
            text += out_path.read_text(encoding="utf-8", errors="replace")
        origin = parse_cloudflared_origin(text)
        if origin:
            return origin
        time.sleep(0.4)
    return None


def _open_tv_launcher(root: Path, url: str) -> None:
    settings = load_settings(root / "config" / "settings.json")
    chrome = resolve_application_paths(settings).get("chrome")
    if chrome is None:
        print("找不到 Chrome，改用系統預設瀏覽器開啟電視啟動器。")
        webbrowser.open(url)
        return
    arguments = chrome_launcher_args(
        chrome,
        url,
        root / "config" / "chrome-launcher-profile",
    )
    subprocess.Popen(arguments)


def install_autostart(*, root: Path | None = None, remove: bool = False) -> None:
    base = root or project_root()
    if os.name == "nt":
        script = base / "scripts" / "install-autostart.ps1"
        arguments = ["powershell", "-NoProfile", "-File", str(script)]
        if remove:
            arguments.append("-Remove")
        _run(arguments)
        return
    python = venv_python(base)
    start_command = [
        str(python),
        str(base / "freetv.py"),
        "start",
        "--no-browser",
        "--supervise",
    ]
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "gg.freetv.plist"
        if remove:
            subprocess.run(["launchctl", "unload", str(plist)], check=False)
            if plist.exists():
                plist.unlink()
            print(f"Removed {plist}")
            return
        plist.parent.mkdir(parents=True, exist_ok=True)
        arguments_xml = "\n".join(f"    <string>{item}</string>" for item in start_command)
        plist.write_text(
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0"><dict>\n'
                "  <key>Label</key><string>gg.freetv</string>\n"
                "  <key>ProgramArguments</key><array>\n"
                f"{arguments_xml}\n"
                "  </array>\n"
                f"  <key>WorkingDirectory</key><string>{base}</string>\n"
                "  <key>RunAtLoad</key><true/>\n"
                "  <key>KeepAlive</key><true/>\n"
                "</dict></plist>\n"
            ),
            encoding="utf-8",
        )
        subprocess.run(["launchctl", "load", str(plist)], check=False)
        print(f"Installed {plist}")
        return

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit = unit_dir / "freetv.service"
    if remove:
        subprocess.run(["systemctl", "--user", "disable", "--now", "freetv.service"], check=False)
        if unit.exists():
            unit.unlink()
        print(f"Removed {unit}")
        return
    unit_dir.mkdir(parents=True, exist_ok=True)
    exec_start = " ".join(start_command)
    unit.write_text(
        (
            "[Unit]\n"
            "Description=FreeTV set-top box\n"
            "After=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"WorkingDirectory={base}\n"
            f"ExecStart={exec_start}\n"
            "Restart=on-failure\n"
            "RestartSec=60\n"
            "StartLimitBurst=3\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        ),
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "freetv.service"], check=False)
    print(f"Installed {unit}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把這台電腦變成可攜式電視機上盒。",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="建立虛擬環境、安裝依賴並準備設定檔")
    start = subparsers.add_parser("start", help="啟動控制器並開啟電視畫面")
    start.add_argument("--no-browser", action="store_true")
    start.add_argument("--no-tunnel", action="store_true")
    start.add_argument("--supervise", action="store_true")
    subparsers.add_parser("doctor", help="檢查這台電腦能不能當機上盒")
    autostart = subparsers.add_parser("autostart", help="登入後自動啟動")
    autostart.add_argument("--remove", action="store_true")
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    command = arguments.command or "run"
    try:
        if command in {"run", "setup"}:
            setup_appliance()
            if command == "setup":
                return 0
        if command in {"run", "start"}:
            no_browser = bool(getattr(arguments, "no_browser", False))
            no_tunnel = bool(getattr(arguments, "no_tunnel", False))
            supervise = bool(getattr(arguments, "supervise", False))
            return start_appliance(
                no_browser=no_browser,
                no_tunnel=no_tunnel,
                supervise=supervise,
            )
        if command == "doctor":
            print_doctor()
            return 0
        if command == "autostart":
            install_autostart(remove=bool(arguments.remove))
            return 0
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    parser.error(f"Unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
