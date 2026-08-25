from __future__ import annotations

from app.applications.adblock import ADBLOCK_EXTENSION_ID, ADBLOCK_YOUTUBE_EXTENSION_ID
from app.applications.chrome_policy import apply_force_install, force_install_entries


def test_force_install_entries_cover_both_store_ids() -> None:
    entries = dict(force_install_entries())
    assert entries["1"].startswith(f"{ADBLOCK_EXTENSION_ID};")
    assert entries["2"].startswith(f"{ADBLOCK_YOUTUBE_EXTENSION_ID};")
    assert entries["1"].endswith("https://clients2.google.com/service/update2/crx")


def test_apply_force_install_writes_each_entry() -> None:
    written: dict[str, str] = {}
    result = apply_force_install(writer=written.__setitem__)
    assert dict(result) == written
    assert ADBLOCK_EXTENSION_ID in written["1"]
    assert ADBLOCK_YOUTUBE_EXTENSION_ID in written["2"]
