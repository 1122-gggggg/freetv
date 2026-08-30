#!/usr/bin/env sh
set -eu
command -v python3 >/dev/null 2>&1 || { echo 'FreeTV needs Python 3.11+ (python3).' >&2; exit 1; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' || { echo 'FreeTV needs Python 3.11+.' >&2; exit 1; }

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname "$0")" && pwd)
if [ -f "$SCRIPT_DIR/freetv.py" ] &&
  [ -f "$SCRIPT_DIR/VERSION" ] &&
  [ -f "$SCRIPT_DIR/backend/app/installer.py" ]; then
  exec python3 "$SCRIPT_DIR/freetv.py" install
fi

command -v curl >/dev/null 2>&1 || { echo 'FreeTV installer needs curl.' >&2; exit 1; }
command -v unzip >/dev/null 2>&1 || { echo 'FreeTV installer needs unzip.' >&2; exit 1; }
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/freetv-install.XXXXXX")
trap 'rm -rf "$TEMP_DIR"' EXIT HUP INT TERM
BASE_URL=https://github.com/1122-gggggg/freetv/releases/latest/download
curl --fail --location --proto '=https' --proto-redir '=https' --silent --show-error "$BASE_URL/pc-tv-box.zip" --output "$TEMP_DIR/pc-tv-box.zip"
curl --fail --location --proto '=https' --proto-redir '=https' --silent --show-error "$BASE_URL/pc-tv-box.zip.sha256" --output "$TEMP_DIR/pc-tv-box.zip.sha256"
EXPECTED=$(awk 'NR == 1 { print tolower($1) }' "$TEMP_DIR/pc-tv-box.zip.sha256")
if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL=$(sha256sum "$TEMP_DIR/pc-tv-box.zip" | awk '{ print tolower($1) }')
else
  ACTUAL=$(shasum -a 256 "$TEMP_DIR/pc-tv-box.zip" | awk '{ print tolower($1) }')
fi
[ "$EXPECTED" = "$ACTUAL" ] || { echo 'FreeTV installer checksum verification failed.' >&2; exit 1; }
unzip -q "$TEMP_DIR/pc-tv-box.zip" -d "$TEMP_DIR"
python3 "$TEMP_DIR/pc-tv-box/freetv.py" install
