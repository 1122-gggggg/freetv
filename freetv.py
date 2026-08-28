#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.stderr.write("FreeTV 需要 Python 3.11 或更新版本。\n")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.appliance import main

if __name__ == "__main__":
    raise SystemExit(main())
