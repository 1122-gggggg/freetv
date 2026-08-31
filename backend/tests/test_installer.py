import importlib.util
import hashlib
import json
import os
from pathlib import Path

import pytest

from app import installer
from app.installer import (
    apply_pending_update,
    bundled_runtime_python,
    copy_release_files,
    create_user_launcher,
    is_bundled_runtime,
    launch_pending_installer_update,
    managed_files,
    pending_installer_marker,
    user_install_directory,
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



def pending_installer(
    root: Path, *, version: str = "v0.4.2", content: bytes = b"MZ-installer"
) -> tuple[Path, Path, str]:
    updates = root / "config" / "updates"
    updates.mkdir(parents=True)
    source = updates / "FreeTV-Setup-v0.4.2.exe"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    marker = pending_installer_marker(root)
    marker.write_text(
        json.dumps({"version": version, "installer": str(source), "sha256": digest}),
        encoding="utf-8",
    )
    return marker, source, digest


def test_pending_installer_rejects_malformed_marker(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    marker = pending_installer_marker(root)
    marker.parent.mkdir(parents=True)
    marker.write_text("{not-json", encoding="utf-8")

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()


def test_pending_installer_rejects_reparse_update_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    outside = tmp_path / "outside"
    outside.mkdir()
    config = root / "config"
    config.mkdir(parents=True)
    updates = config / "updates"
    try:
        updates.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable")
    source = outside / "FreeTV-Setup.exe"
    source.write_bytes(b"MZ-reparse")
    marker = outside / "pending-installer-update.json"
    marker.write_text(
        json.dumps(
            {
                "version": "v0.4.2",
                "installer": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (root / "VERSION").write_text("0.4.1")
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: False if path == updates else real_is_symlink(path),
    )

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()


def test_pending_installer_rejects_source_outside_update_dir(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    marker, source, digest = pending_installer(root)
    outside = tmp_path / "outside.exe"
    outside.write_bytes(source.read_bytes())
    marker.write_text(
        json.dumps({"version": "v0.4.2", "installer": str(outside), "sha256": digest}),
        encoding="utf-8",
    )

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()
    assert outside.exists()


def test_pending_installer_rejects_changed_digest(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root)
    source.write_bytes(b"MZ-tampered")

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()
    assert source.exists()


def test_pending_installer_rejects_oversized_source(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root, content=b"MZ-oversized")
    monkeypatch.setattr(installer, "MAX_INSTALLER_BYTES", 4)

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()
    assert source.exists()


def test_pending_installer_rejects_non_newer_target(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root, version="v0.4.0")
    (root / "VERSION").write_text("0.4.1")

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()
    assert source.exists()


def test_pending_installer_launches_verified_copy_with_update_flags(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, digest = pending_installer(root)
    (root / "VERSION").write_text("0.4.1")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(installer.tempfile, "gettempdir", lambda: str(temporary))
    launches: list[tuple[list[str], dict[str, object]]] = []

    def capture(command: list[str], **kwargs: object) -> object:
        launches.append((command, kwargs))
        return object()

    assert launch_pending_installer_update(root, popen=capture, os_name="nt")
    command, options = launches[0]
    copied = Path(command[0])

    assert command[1:] == [
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/UPDATE=1",
        '/MERGETASKS="!appliancepower"',
    ]
    assert copied.parent == temporary / "FreeTV-updates"
    assert copied.name.startswith("FreeTV-update-")
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == digest
    assert options["close_fds"] is True
    assert options["creationflags"]
    assert marker.exists()
    assert source.exists()


def test_pending_installer_launch_failure_keeps_retry_marker_and_source(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root)
    (root / "VERSION").write_text("0.4.1")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(installer.tempfile, "gettempdir", lambda: str(temporary))

    def fail_launch(*args: object, **kwargs: object) -> object:
        raise OSError("simulated launch failure")

    assert not launch_pending_installer_update(root, popen=fail_launch, os_name="nt")
    assert marker.exists()
    assert source.exists()
    assert source.read_bytes() == b"MZ-installer"


def test_pending_installer_copy_hash_failure_keeps_retry_state(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root)
    (root / "VERSION").write_text("0.4.1")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(installer.tempfile, "gettempdir", lambda: str(temporary))
    real_hash = installer._hash_installer

    def mismatch_copy(path: Path) -> tuple[int, str]:
        size, digest = real_hash(path)
        return (size, digest) if path == source else (size, "0" * 64)

    monkeypatch.setattr(installer, "_hash_installer", mismatch_copy)

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()
    assert source.exists()


def test_pending_installer_copy_and_cleanup_failures_do_not_crash_bootstrap(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root)
    (root / "VERSION").write_text("0.4.1")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(installer.tempfile, "gettempdir", lambda: str(temporary))
    copied: Path | None = None

    def fail_copy(source_path: Path, destination: Path, **kwargs: object) -> None:
        nonlocal copied
        copied = Path(destination)
        raise OSError("simulated copy failure")

    real_unlink = Path.unlink

    def fail_temp_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if copied is not None and path == copied:
            raise OSError("simulated cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(installer.shutil, "copy2", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_temp_cleanup)

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert marker.exists()
    assert source.exists()


def test_completed_installer_update_cleans_marker_source_and_old_temp_copies(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root, version="v0.4.2")
    (root / "VERSION").write_text("0.4.2")
    temporary = tmp_path / "temporary"
    old_updates = temporary / "FreeTV-updates"
    old_updates.mkdir(parents=True)
    old_copy = old_updates / "FreeTV-update-old.exe"
    old_copy.write_bytes(b"old")
    monkeypatch.setattr(installer.tempfile, "gettempdir", lambda: str(temporary))

    assert not launch_pending_installer_update(
        root,
        popen=lambda *args, **kwargs: pytest.fail(f"unexpected launch: {args} {kwargs}"),
        os_name="nt",
    )
    assert not marker.exists()
    assert not source.exists()
    assert not old_copy.exists()


def test_completed_installer_cleanup_retries_source_before_removing_marker(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root, version="v0.4.2")
    (root / "VERSION").write_text("0.4.2")
    real_unlink = Path.unlink
    failures = 0

    def fail_source_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failures
        if path == source and failures == 0:
            failures += 1
            raise OSError("simulated locked source")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_source_once)
    no_launch = lambda *args, **kwargs: pytest.fail(
        f"unexpected launch: {args} {kwargs}"
    )

    assert not launch_pending_installer_update(root, popen=no_launch, os_name="nt")
    assert marker.exists()
    assert source.exists()

    assert not launch_pending_installer_update(root, popen=no_launch, os_name="nt")
    assert not marker.exists()
    assert not source.exists()


def test_completed_installer_cleanup_retries_marker_after_source_is_gone(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "installed"
    marker, source, _ = pending_installer(root, version="v0.4.2")
    (root / "VERSION").write_text("0.4.2")
    real_unlink = Path.unlink
    marker_failures = 0

    def fail_marker_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal marker_failures
        if path == marker and marker_failures == 0:
            marker_failures += 1
            raise OSError("simulated locked marker")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_marker_once)
    no_launch = lambda *args, **kwargs: pytest.fail(
        f"unexpected launch: {args} {kwargs}"
    )

    assert not launch_pending_installer_update(root, popen=no_launch, os_name="nt")
    assert marker.exists()
    assert not source.exists()

    assert not launch_pending_installer_update(root, popen=no_launch, os_name="nt")
    assert not marker.exists()
    assert not source.exists()


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


@pytest.mark.parametrize("arguments", [["start"], ["doctor"], ["autostart"]])
def test_applied_update_in_bundled_runtime_finalizes_before_forwarding(
    arguments: list[str], monkeypatch
) -> None:
    application_calls: list[list[str]] = []
    monkeypatch.setattr(freetv, "UPDATE_APPLIED", True)
    monkeypatch.setattr(freetv, "is_bundled_runtime", lambda root: True)
    monkeypatch.setattr(
        freetv,
        "_run_application",
        lambda raw_arguments: application_calls.append(raw_arguments) or 0,
    )
    monkeypatch.setattr(
        freetv,
        "_run",
        lambda command: pytest.fail(f"unexpected legacy bootstrap command: {command}"),
    )

    assert freetv.main(arguments) == 0
    assert application_calls == [["setup"], arguments]


def test_applied_update_in_bundled_runtime_stops_when_finalization_fails(
    monkeypatch,
) -> None:
    application_calls: list[list[str]] = []
    monkeypatch.setattr(freetv, "UPDATE_APPLIED", True)
    monkeypatch.setattr(freetv, "is_bundled_runtime", lambda root: True)
    monkeypatch.setattr(
        freetv,
        "_run_application",
        lambda raw_arguments: application_calls.append(raw_arguments) or 7,
    )
    monkeypatch.setattr(
        freetv,
        "_run",
        lambda command: pytest.fail(f"unexpected legacy bootstrap command: {command}"),
    )

    assert freetv.main(["start"]) == 7
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
