"""Stdlib-only release installation primitives."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import stat
import sys
import tempfile
from collections.abc import Callable
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
MAX_INSTALLER_BYTES = 250 * 1024 * 1024


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



def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(
        attributes
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x00000400)
    )


def _safe_update_boundaries(root: Path, config: Path, updates: Path) -> bool:
    try:
        return (
            config.is_dir()
            and updates.is_dir()
            and not config.is_symlink()
            and not updates.is_symlink()
            and not _is_reparse_point(config)
            and not _is_reparse_point(updates)
            and _inside(config, root)
            and _inside(updates, root)
        )
    except OSError:
        return False


def pending_installer_marker(root: Path) -> Path:
    return root / "config" / "updates" / "pending-installer-update.json"


def _hash_installer(path: Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_INSTALLER_BYTES:
                raise ValueError("installer is too large")
            digest.update(chunk)
    if size == 0:
        raise ValueError("installer is empty")
    return size, digest.hexdigest()


def _version_parts(value: str) -> tuple[int, ...]:
    parts = value.strip().lstrip("vV").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError("invalid version")
    return tuple(int(part) for part in parts)


def _cleanup_temp_installers() -> None:
    updates = Path(tempfile.gettempdir()) / "FreeTV-updates"
    if (
        updates.is_symlink()
        or _is_reparse_point(updates)
        or not updates.is_dir()
    ):
        return
    for candidate in updates.glob("FreeTV-update-*.exe"):
        try:
            if candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
        except OSError:
            pass


def launch_pending_installer_update(
    root: Path,
    *,
    popen: Callable[..., object] = subprocess.Popen,
    os_name: str = os.name,
) -> bool:
    if os_name != "nt":
        return False
    config = root / "config"
    updates = config / "updates"
    marker = pending_installer_marker(root)
    copied: Path | None = None
    if (
        not _safe_update_boundaries(root, config, updates)
        or marker.is_symlink()
        or _is_reparse_point(marker)
        or not marker.is_file()
    ):
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        version = str(payload["version"]).strip()
        expected_digest = str(payload["sha256"]).strip()
        source = Path(str(payload["installer"])).expanduser()
        source = source if source.is_absolute() else marker.parent / source
        if (
            not _inside(source, updates)
            or source.is_symlink()
            or _is_reparse_point(source)
            or len(expected_digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in expected_digest)
        ):
            return False
        installed_version = (root / "VERSION").read_text(encoding="utf-8").strip()
        target_parts = _version_parts(version)
        installed_parts = _version_parts(installed_version)
        try:
            source_stat = source.stat(follow_symlinks=False)
        except FileNotFoundError:
            source_stat = None
        if target_parts == installed_parts:
            if source_stat is not None:
                if not stat.S_ISREG(source_stat.st_mode):
                    return False
                _, source_digest = _hash_installer(source)
                if source_digest.lower() != expected_digest.lower():
                    return False
                try:
                    source.unlink()
                except OSError:
                    return False
            try:
                marker.unlink()
            except OSError:
                return False
            _cleanup_temp_installers()
            return False
        if target_parts <= installed_parts or source_stat is None:
            return False
        if not stat.S_ISREG(source_stat.st_mode):
            return False
        source_size, source_digest = _hash_installer(source)
        if source_digest.lower() != expected_digest.lower():
            return False
        temporary_updates = Path(tempfile.gettempdir()) / "FreeTV-updates"
        if temporary_updates.is_symlink() or _is_reparse_point(temporary_updates):
            return False
        temporary_updates.mkdir(parents=True, exist_ok=True)
        descriptor, copied_name = tempfile.mkstemp(
            prefix="FreeTV-update-",
            suffix=".exe",
            dir=temporary_updates,
        )
        os.close(descriptor)
        copied = Path(copied_name)
        shutil.copy2(source, copied, follow_symlinks=False)
        copied_size, copied_digest = _hash_installer(copied)
        if copied_size != source_size or copied_digest.lower() != source_digest.lower():
            raise ValueError("copied installer checksum mismatch")
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
        popen(
            [
                str(copied),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/UPDATE=1",
                '/MERGETASKS="!appliancepower"',
            ],
            close_fds=True,
            creationflags=creationflags,
        )
        return True
    except (OSError, ValueError, KeyError, TypeError):
        if copied is not None:
            try:
                copied.unlink(missing_ok=True)
            except OSError:
                pass
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
