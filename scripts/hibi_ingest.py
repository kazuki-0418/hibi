#!/usr/bin/env python3
"""List or summarize raw Hibi captures under the Obsidian vault (KAZ-204 v0).

Usage:
    python scripts/hibi_ingest.py

Reads ``30_raw/hibi/capture/`` and ``30_raw/hibi/inbox/`` without mutating
``decisions.md`` (centroid self-pollution guard).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from goals.vault_io import CAPTURE_SUBPATH, INBOX_SUBPATH

load_dotenv()


def _list_dir(root: Path, subpath: str) -> list[Path]:
    folder = root / subpath
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.md"))


def main() -> int:
    vault = os.environ.get("OBSIDIAN_VAULT_ROOT")
    if not vault:
        print("OBSIDIAN_VAULT_ROOT is not set.")
        return 1

    root = Path(vault)
    captures = _list_dir(root, CAPTURE_SUBPATH)
    inbox = _list_dir(root, INBOX_SUBPATH)

    print(f"Vault: {root}")
    print(f"\nCapture ({CAPTURE_SUBPATH}): {len(captures)} file(s)")
    for path in captures[-10:]:
        print(f"  - {path.name}")

    print(f"\nNovelty inbox ({INBOX_SUBPATH}): {len(inbox)} file(s)")
    for path in inbox[-10:]:
        print(f"  - {path.name}")

    print("\nEdit captures manually; do not auto-append to decisions.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
