#!/usr/bin/env python3
"""Stdlib-only bootstrap: creates the venv, then re-execs under it.

Everything that imports application code (Pydantic, FastAPI) runs under the
venv interpreter, so `python freetv.py setup` works on a clean machine.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

MINIMUM_PYTHON = (3, 11)
ROOT = Path(__file__).resolve().parent


def venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把這台電腦變成可攜式電視機上盒。")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="建立虛擬環境、安裝依賴並準備設定檔")
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


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        sys.stderr.write(
            f"FreeTV 需要 Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} 或更新版本。\n"
        )
        return 2
    arguments = parse_arguments(list(argv) if argv is not None else sys.argv[1:])
    command = arguments.command or "run"
    python = venv_python()

    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        if not python.is_file():
            if command not in {"setup", "run"}:
                sys.stderr.write("找不到虛擬環境。請先執行 python freetv.py setup。\n")
                return 1
            print(f"Creating virtual environment at {ROOT / '.venv'}...")
            code = _run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
            if code != 0:
                return code
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
        code = _run([str(python), str(ROOT / "freetv.py"), *sys.argv[1:]])
        return code

    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.appliance import main as appliance_main
    except ImportError:
        sys.stderr.write("虛擬環境不完整。請重新執行 python freetv.py setup。\n")
        return 1

    return appliance_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
