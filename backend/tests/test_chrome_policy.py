from __future__ import annotations

from app.applications.chrome_policy import (
    ADBLOCK_EXTENSION_ID,
    STORE_UPDATE_URL,
    TV_CHROME_NOTIFICATION_FLAGS,
    apply_force_install,
    force_install_entries,
)


def test_tv_notification_flags_are_fixed_and_minimal() -> None:
    assert TV_CHROME_NOTIFICATION_FLAGS == [
        "--disable-notifications",
        "--deny-permission-prompts",
    ]


def test_force_install_entries_contains_only_primary_store_id() -> None:
    entries = dict(force_install_entries())
    assert entries == {"1": f"{ADBLOCK_EXTENSION_ID};{STORE_UPDATE_URL}"}


def test_apply_force_install_writes_only_primary_entry() -> None:
    written: dict[str, str] = {}
    result = apply_force_install(writer=written.__setitem__)
    assert dict(result) == written == {
        "1": f"{ADBLOCK_EXTENSION_ID};{STORE_UPDATE_URL}"
    }
