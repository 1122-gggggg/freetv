import importlib.util
import json
import os
from pathlib import Path

import pytest

from app import installer
from app.installer import (
    bundled_runtime_python,
    apply_pending_update,
    copy_release_files,
    create_user_launcher,
    managed_files,
    user_install_directory,
    is_bundled_runtime,
)

FREETV_PATH = Path(__file__).resolve().parents[2] / "freetv.py"
FREETV_SPEC = importlib.util.spec_from_file_location("freetv_bootstrap_test", FREETV_PATH)
assert FREETV_SPEC is not None and FREETV_SPEC.loader is not None
freetv = importlib.util.module_from_spec(FREETV_SPEC)
FREETV_SPEC.loader.exec_module(freetv)

def test_bundled_runtime_paths_are_private_to_install_root(tmp_path: Path) -> None:
    assert bundled_runtime_python(tmp_path, os_name="nt") == tmp_path / "runtime" / "python.exe"
    assert bundled_runtime_python(tmp_path, windowed=True, os_name="nt") == (
        tmp_path / "runtime" / "pythonw.exe"
    )


def test_bundled_runtime_detection_accepts_python_and_pythonw(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("python.exe", "pythonw.exe"):
        executable = runtime / name
        executable.touch()
        assert is_bundled_runtime(tmp_path, executable=executable, os_name="nt")



def test_copy_release_files_preserves_user_data(tmp_path: Path) -> None:
    source, target = tmp_path / "package", tmp_path / "installed"
    (source / "config").mkdir(parents=True)
    (source / "backend" / "app").mkdir(parents=True)
    (source / "config" / "settings.example.json").write_text("{}")
    (source / "backend" / "app" / "new.py").write_text("new")
    (target / "config").mkdir(parents=True)
    (target / "config" / "settings.json").write_text("user")
    (target / ".venv").mkdir()
    copy_release_files(source, target)
    assert (target / "backend" / "app" / "new.py").read_text() == "new"
    assert (target / "config" / "settings.json").read_text() == "user"
    assert (target / ".venv").is_dir()
    assert "config/settings.json" not in managed_files(source)


def test_pending_update_rejects_staging_outside_update_dir(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    marker = config / "pending-update.json"
    marker.write_text('{"staging": "../../evil"}')
    assert apply_pending_update(tmp_path) is False
    assert marker.exists()


def test_user_install_directory_is_platform_scoped(tmp_path: Path) -> None:
    assert user_install_directory("posix", tmp_path / "home") == (
        tmp_path / "home" / ".local" / "share" / "freetv"
    )


def test_managed_files_excludes_checkout_and_user_state(tmp_path: Path) -> None:
    source = tmp_path / "package"
    for relative in (
        "freetv.py",
        "backend/app/main.py",
        "frontend/dist/index.html",
        "config/settings.example.json",
        "config/settings.json",
        ".git/config",
        "frontend/node_modules/package/index.js",
        "mobile/App.tsx",
        ".venv/bin/python",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)

    files = managed_files(source)

    assert files == [
        "backend/app/main.py",
        "config/settings.example.json",
        "freetv.py",
        "frontend/dist/index.html",
    ]


def test_pending_update_applies_managed_files_and_preserves_user_state(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    payload = root / "config" / "updates" / "v0.4.0-test" / "pc-tv-box"
    for relative, content in {
        "freetv.py": "new bootstrap",
        "backend/app/main.py": "new backend",
        "frontend/dist/index.html": "new frontend",
        "config/settings.example.json": "new example",
    }.items():
        path = payload / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "settings.json").write_text("user settings")
    (root / ".venv").mkdir()
    (root / "config" / "pending-update.json").write_text(
        json.dumps({"version": "v0.4.0", "staging": str(payload)})
    )

    assert apply_pending_update(root)
    assert (root / "backend" / "app" / "main.py").read_text() == "new backend"
    assert (root / "config" / "settings.json").read_text() == "user settings"
    assert (root / ".venv").is_dir()
    assert not (root / "config" / "pending-update.json").exists()
    assert not payload.parent.exists()


def test_pending_update_rolls_back_partial_copy_and_keeps_marker(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    payload = root / "config" / "updates" / "v0.4.0-test" / "pc-tv-box"
    for relative, content in {
        "freetv.py": "new bootstrap",
        "backend/app/main.py": "new backend",
    }.items():
        path = payload / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "freetv.py").write_text("old bootstrap")
    marker = root / "config" / "pending-update.json"
    marker.write_text(json.dumps({"staging": str(payload)}))
    real_copy = installer.shutil.copy2

    def fail_bootstrap_copy(source: Path, target: Path):
        if Path(source) == payload / "freetv.py":
            raise OSError("simulated disk failure")
        return real_copy(source, target)

    monkeypatch.setattr(installer.shutil, "copy2", fail_bootstrap_copy)

    assert not apply_pending_update(root)
    assert (root / "freetv.py").read_text() == "old bootstrap"
    assert not (root / "backend" / "app" / "main.py").exists()
    assert marker.exists()


def test_copy_release_files_rejects_symlinked_destination_parent(tmp_path: Path) -> None:
    source = tmp_path / "package"
    target = tmp_path / "installed"
    outside = tmp_path / "outside"
    (source / "backend" / "app").mkdir(parents=True)
    (source / "backend" / "app" / "main.py").write_text("new backend")
    outside.mkdir()
    target.mkdir()
    (target / "backend").symlink_to(outside, target_is_directory=True)

    try:
        with pytest.raises(ValueError, match="symbolic link"):
            copy_release_files(source, target)
    finally:
        (target / "backend").unlink(missing_ok=True)

    assert not (outside / "app" / "main.py").exists()


def test_user_launcher_runs_the_installed_virtual_environment(tmp_path: Path) -> None:
    target = tmp_path / "Free TV"
    launcher = create_user_launcher(target, "posix", tmp_path / "home")
    content = launcher.read_text()

    assert str(target / ".venv" / "bin" / "python") in content
    assert str(target / "freetv.py") in content
    if os.name != "nt":
        assert launcher.stat().st_mode & 0o111


def test_install_command_sets_up_launcher_and_starts_installed_copy(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "installed"
    copied: list[tuple[Path, Path]] = []
    launched: list[Path] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(freetv, "user_install_directory", lambda: target)
    monkeypatch.setattr(
        freetv,
        "copy_release_files",
        lambda source, destination: copied.append((source, destination)),
    )
    monkeypatch.setattr(
        freetv,
        "create_user_launcher",
        lambda destination: launched.append(destination) or (tmp_path / "FreeTV.desktop"),
    )
    monkeypatch.setattr(
        freetv,
        "_run",
        lambda command: commands.append(command) or 0,
    )

    assert freetv.main(["install"]) == 0
    assert copied == [(freetv.ROOT, target)]
    assert launched == [target]
    assert [command[-1] for command in commands] == ["setup", "autostart", "start"]



def test_setup_repairs_an_existing_partial_virtual_environment(
    tmp_path: Path, monkeypatch
) -> None:
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    commands: list[list[str]] = []
    monkeypatch.setattr(freetv, "venv_python", lambda: python)
    monkeypatch.setattr(freetv.sys, "prefix", freetv.sys.base_prefix)
    monkeypatch.setattr(
        freetv,
        "_run",
        lambda command: commands.append(command) or 0,
    )

    assert freetv.main(["setup"]) == 0
    assert commands[0][1:4] == ["-m", "pip", "install"]
    assert commands[1][1:5] == ["-m", "pip", "install", "-r"]
    assert commands[2] == [str(python), str(freetv.ROOT / "freetv.py"), "setup"]

def test_bundled_runtime_runs_application_without_venv_bootstrap(monkeypatch) -> None:
    application_calls: list[list[str]] = []
    monkeypatch.setattr(freetv, "is_bundled_runtime", lambda root: True)
    monkeypatch.setattr(
        freetv,
        "_run_application",
        lambda arguments: application_calls.append(arguments) or 0,
    )
    monkeypatch.setattr(
        freetv,
        "_run",
        lambda command: pytest.fail(f"unexpected bootstrap command: {command}"),
    )

    assert freetv.main(["setup"]) == 0
    assert application_calls == [["setup"]]



def test_bundled_runtime_install_finalizes_without_legacy_bootstrap(
    tmp_path: Path, monkeypatch
) -> None:
    application_calls: list[list[str]] = []
    monkeypatch.setattr(freetv, "is_bundled_runtime", lambda root: True)
    monkeypatch.setattr(freetv, "user_install_directory", lambda: tmp_path / "installed")
    monkeypatch.setattr(
        freetv,
        "_run_application",
        lambda arguments: application_calls.append(arguments) or 0,
    )
    monkeypatch.setattr(
        freetv,
        "copy_release_files",
        lambda *args: pytest.fail(f"unexpected legacy install copy: {args}"),
    )
    monkeypatch.setattr(
        freetv,
        "_run",
        lambda command: pytest.fail(f"unexpected bootstrap command: {command}"),
    )

    assert freetv.main(["install"]) == 0
    assert application_calls == [["setup"]]


def test_applied_update_finishes_dependency_setup_before_start(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(freetv, "UPDATE_APPLIED", True)
    monkeypatch.setattr(
        freetv,
        "_run",
        lambda command: commands.append(command) or 7,
    )

    assert freetv.main(["start"]) == 7
    assert commands[0][-1] == "setup"
