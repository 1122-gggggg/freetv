"""Stdlib-only release installation primitives."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

MANAGED_ROOT_FILES = {
    "freetv.py",
    "run.sh",
    "run.cmd",
    "run.ps1",
    "install.sh",
    "Install-FreeTV.cmd",
    "Install-FreeTV.ps1",
    "README.md",
    "VERSION",
}
MANAGED_TREES = ("backend/app", "frontend/dist", "scripts", "docs")
MANAGED_SINGLE_FILES = (
    "backend/requirements.txt",
    "config/settings.example.json",
    "config/channels.example.json",
    "config/news.example.json",
)


def bundled_runtime_python(
    root: Path, *, windowed: bool = False, os_name: str = os.name
) -> Path:
    name = "pythonw.exe" if windowed else "python.exe"
    return root / "runtime" / name if os_name == "nt" else root / "runtime" / "bin" / "python"


def is_bundled_runtime(
    root: Path,
    *,
    executable: Path | None = None,
    os_name: str = os.name,
) -> bool:
    if os_name != "nt":
        return False
    current = (executable or Path(sys.executable)).resolve()
    return current in {
        bundled_runtime_python(root, os_name=os_name).resolve(),
        bundled_runtime_python(root, windowed=True, os_name=os_name).resolve(),
    }


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def managed_files(source: Path) -> list[str]:
    """Return release-managed relative paths, excluding user state."""
    result: set[str] = set()
    for name in MANAGED_ROOT_FILES:
        if (source / name).is_file() and not (source / name).is_symlink():
            result.add(name)
    for name in MANAGED_SINGLE_FILES:
        if (source / name).is_file() and not (source / name).is_symlink():
            result.add(name)
    for tree in MANAGED_TREES:
        root = source / tree
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".pyo"}
            ):
                result.add(path.relative_to(source).as_posix())
    return sorted(result)


def _safe_destination(root: Path, relative: str) -> Path:
    destination = root / relative
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("managed destination contains a symbolic link")
    if not _inside(destination, root):
        raise ValueError("managed destination escapes the installation directory")
    return destination


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".freetv-copy",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary, follow_symlinks=False)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def copy_release_files(source: Path, target: Path) -> list[Path]:
    copied: list[Path] = []
    for relative in managed_files(source):
        src = source / relative
        dst = _safe_destination(target, relative)
        _atomic_copy(src, dst)
        copied.append(dst)
    return copied


def apply_pending_update(root: Path) -> bool:
    config = root / "config"
    if config.is_symlink() or (config / "updates").is_symlink():
        return False
    marker = config / "pending-update.json"
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        staging = Path(str(payload["staging"])).expanduser()
        update_dir = (config / "updates").resolve()
        staging = staging if staging.is_absolute() else (marker.parent / staging)
        if not _inside(staging, update_dir) or not staging.is_dir():
            return False
        # Archives commonly extract a single pc-tv-box directory.
        payload_root = staging / "pc-tv-box" if (staging / "pc-tv-box").is_dir() else staging
        planned = managed_files(payload_root)
        if not planned:
            return False
        backup = config / "updates" / ".rollback"
        if backup.exists():
            shutil.rmtree(backup)
        backup.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        for relative in planned:
            existing = _safe_destination(root, relative)
            if existing.is_file():
                saved = _safe_destination(backup, relative)
                _atomic_copy(existing, saved)
            else:
                created.append(existing)
        try:
            copy_release_files(payload_root, root)
        except (OSError, ValueError):
            for relative in planned:
                saved = backup / relative
                if saved.is_file():
                    destination = _safe_destination(root, relative)
                    _atomic_copy(saved, destination)
            for destination in created:
                if destination.is_file():
                    destination.unlink()
            return False
        shutil.rmtree(backup, ignore_errors=True)
        marker_removed = True
        try:
            marker.unlink()
        except OSError:
            # Managed files are already fully copied. Report success so the
            # bootstrap refreshes dependencies; a retained marker only causes
            # the same verified payload to be retried on a later start.
            marker_removed = False
        if marker_removed and staging.parent.parent == update_dir:
            shutil.rmtree(staging.parent, ignore_errors=True)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def user_install_directory(os_name: str = os.name, home: Path | None = None) -> Path:
    home = home or Path.home()
    if os_name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "FreeTV"
    if os_name == "darwin":
        return home / "Library" / "Application Support" / "FreeTV"
    return home / ".local" / "share" / "freetv"


def create_user_launcher(target: Path, os_name: str = os.name, home: Path | None = None) -> Path:
    home = home or Path.home()
    if os_name == "nt":
        launcher = (
            Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "FreeTV.cmd"
        )
        runtime = target / ".venv" / "Scripts" / "python.exe"
        content = f'@echo off\r\nstart "FreeTV" "{runtime}" "{target / "freetv.py"}" start\r\n'
    elif os_name == "darwin":
        launcher = home / "Applications" / "FreeTV.command"
        runtime = target / ".venv" / "bin" / "python"
        content = f'#!/bin/sh\nexec "{runtime}" "{target / "freetv.py"}" start\n'
    else:
        launcher = home / ".local" / "share" / "applications" / "freetv.desktop"
        runtime = target / ".venv" / "bin" / "python"
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=FreeTV\n"
            f'Exec="{runtime}" "{target / "freetv.py"}" start\n'
            "Terminal=false\n"
        )
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(content, encoding="utf-8")
    if os_name != "nt":
        launcher.chmod(0o755)
    return launcher
