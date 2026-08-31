#!/usr/bin/env python3
"""Stdlib-only bootstrap: creates the venv, then re-execs under it.

Everything that imports application code (Pydantic, FastAPI) runs under the
venv interpreter, so `python freetv.py setup` works on a clean machine.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_INSTALLER_SPEC = importlib.util.spec_from_file_location(
    "freetv_installer", Path(__file__).resolve().parent / "backend" / "app" / "installer.py"
)
assert _INSTALLER_SPEC and _INSTALLER_SPEC.loader
_INSTALLER = importlib.util.module_from_spec(_INSTALLER_SPEC)
_INSTALLER_SPEC.loader.exec_module(_INSTALLER)
apply_pending_update = _INSTALLER.apply_pending_update
bundled_runtime_python = _INSTALLER.bundled_runtime_python
copy_release_files = _INSTALLER.copy_release_files
user_install_directory = _INSTALLER.user_install_directory
create_user_launcher = _INSTALLER.create_user_launcher
is_bundled_runtime = _INSTALLER.is_bundled_runtime

MINIMUM_PYTHON = (3, 11)
ROOT = Path(__file__).resolve().parent

# Keep this import/bootstrap stdlib-only so updates can be applied before the
# virtual environment (and its dependencies) are loaded.
UPDATE_APPLIED = apply_pending_update(ROOT)


def venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把這台電腦變成可攜式電視機上盒。")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="建立虛擬環境、安裝依賴並準備設定檔")
    subparsers.add_parser("install", help="安裝到目前使用者的應用程式目錄")
    start = subparsers.add_parser("start", help="啟動控制器並開啟電視畫面")
    start.add_argument("--no-browser", action="store_true")
    start.add_argument("--no-tunnel", action="store_true")
    start.add_argument("--supervise", action="store_true")
    subparsers.add_parser("doctor", help="檢查這台電腦能不能當機上盒")
    autostart = subparsers.add_parser("autostart", help="登入後自動啟動")
    autostart.add_argument("--remove", action="store_true")
    return parser.parse_args(argv)


def _run(arguments: list[str]) -> int:
    completed = subprocess.run(arguments, check=False)
    return completed.returncode


def _run_application(raw_arguments: list[str]) -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.appliance import main as appliance_main
    except ImportError:
        sys.stderr.write("FreeTV 執行環境不完整。請重新安裝 FreeTV。\n")
        return 1
    return appliance_main(raw_arguments)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        sys.stderr.write(
            f"FreeTV 需要 Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} 或更新版本。\n"
        )
        return 2
    raw_arguments = list(argv) if argv is not None else sys.argv[1:]
    arguments = parse_arguments(raw_arguments)
    command = arguments.command or "run"
    if command == "install":
        target = user_install_directory()
        print(f"Installing FreeTV for this user into {target}")
        if ROOT.resolve() != target.resolve():
            copy_release_files(ROOT, target)
        code = _run([sys.executable, str(target / "freetv.py"), "setup"])
        if code != 0:
            return code
        print(f"Launcher: {create_user_launcher(target)}")
        code = _run([sys.executable, str(target / "freetv.py"), "autostart"])
        if code != 0:
            return code
        return _run([sys.executable, str(target / "freetv.py"), "start"])
    if UPDATE_APPLIED and command != "setup":
        print("Finishing the verified FreeTV update...")
        code = _run([sys.executable, str(ROOT / "freetv.py"), "setup"])
        if code != 0:
            return code
    if is_bundled_runtime(ROOT):
        return _run_application(raw_arguments)
    python = venv_python()

    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        environment_missing = not python.is_file()
        if environment_missing:
            if command not in {"setup", "run"}:
                sys.stderr.write("找不到虛擬環境。請先執行 python freetv.py setup。\n")
                return 1
            print(f"Creating virtual environment at {ROOT / '.venv'}...")
            code = _run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
            if code != 0:
                return code
        if environment_missing or command in {"setup", "run"}:
            print("Installing backend dependencies...")
            code = _run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
            if code == 0:
                code = _run(
                    [
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "-r",
                        str(ROOT / "backend" / "requirements.txt"),
                    ]
                )
            if code != 0:
                return code
        return _run([str(python), str(ROOT / "freetv.py"), *raw_arguments])

    return _run_application(raw_arguments)


if __name__ == "__main__":
    raise SystemExit(main())
