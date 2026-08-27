from __future__ import annotations

import argparse
from collections.abc import Callable

from app.applications.adblock import ADBLOCK_EXTENSION_ID, ADBLOCK_YOUTUBE_EXTENSION_ID

STORE_UPDATE_URL = "https://clients2.google.com/service/update2/crx"
POLICY_KEY = r"Software\Policies\Google\Chrome\ExtensionInstallForcelist"

TV_CHROME_NOTIFICATION_FLAGS = [
    "--disable-notifications",
    "--deny-permission-prompts",
]

FORCE_INSTALL_EXTENSIONS: tuple[tuple[str, str], ...] = (
    (ADBLOCK_EXTENSION_ID, STORE_UPDATE_URL),
    (ADBLOCK_YOUTUBE_EXTENSION_ID, STORE_UPDATE_URL),
)


def force_install_entries() -> list[tuple[str, str]]:
    return [
        (str(index), f"{extension_id};{update_url}")
        for index, (extension_id, update_url) in enumerate(FORCE_INSTALL_EXTENSIONS, start=1)
    ]


def apply_force_install(writer: Callable[[str, str], None] | None = None) -> list[tuple[str, str]]:
    entries = force_install_entries()
    write = writer or _write_hkcu_string
    for name, value in entries:
        write(name, value)
    return entries


def _write_hkcu_string(name: str, value: str) -> None:
    import winreg

    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, POLICY_KEY)
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    finally:
        winreg.CloseKey(key)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="為這個 Windows 使用者強制安裝電視盒用的商店 AdBlock。"
    )
    parser.parse_args()
    installed = apply_force_install()
    for name, value in installed:
        print(f"Chrome policy {name}={value}")


if __name__ == "__main__":
    main()
