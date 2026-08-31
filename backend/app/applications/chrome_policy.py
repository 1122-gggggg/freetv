from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable

ADBLOCK_EXTENSION_ID = "gighmmpiobklfepjocnamgkkbiglidom"
RETIRED_EXTENSION_ID = "cmedhionkhpnakcndndgjdbohmhepckk"

STORE_UPDATE_URL = "https://clients2.google.com/service/update2/crx"
POLICY_KEY = r"Software\Policies\Google\Chrome\ExtensionInstallForcelist"

TV_CHROME_NOTIFICATION_FLAGS = [
    "--disable-notifications",
    "--deny-permission-prompts",
]

FORCE_INSTALL_EXTENSIONS: tuple[tuple[str, str], ...] = (
    (ADBLOCK_EXTENSION_ID, STORE_UPDATE_URL),
)


def force_install_entries() -> list[tuple[str, str]]:
    return [
        (str(index), f"{extension_id};{update_url}")
        for index, (extension_id, update_url) in enumerate(FORCE_INSTALL_EXTENSIONS, start=1)
    ]


def apply_force_install(
    writer: Callable[[str, str], None] | None = None,
    *,
    reader: Callable[[str], str | None] | None = None,
    deleter: Callable[[str], None] | None = None,
) -> list[tuple[str, str]]:
    entries = force_install_entries()
    if writer is None and os.name != "nt":
        return entries
    using_registry = writer is None
    write = writer or _write_hkcu_string
    read = (reader or _read_hkcu_string) if using_registry else reader
    delete = (deleter or _delete_hkcu_value) if using_registry else deleter
    for name, value in entries:
        write(name, value)
    if read is not None and delete is not None:
        legacy_value = read("2")
        if (
            legacy_value is not None
            and legacy_value.partition(";")[0] == RETIRED_EXTENSION_ID
        ):
            delete("2")
    return entries


def _write_hkcu_string(name: str, value: str) -> None:
    import winreg

    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, POLICY_KEY)
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    finally:
        winreg.CloseKey(key)


def _read_hkcu_string(name: str) -> str | None:
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, POLICY_KEY)
    except FileNotFoundError:
        return None
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    finally:
        winreg.CloseKey(key)
    return value if isinstance(value, str) else None


def _delete_hkcu_value(name: str) -> None:
    import winreg

    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, POLICY_KEY)
    try:
        try:
            winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
    finally:
        winreg.CloseKey(key)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="為這個 Windows 使用者強制安裝電視盒用的商店 AdBlock。"
    )
    parser.parse_args()
    installed = apply_force_install()
    for name, value in installed:
        print(f"Chrome policy {name}={value}")


if __name__ == "__main__":
    main()
