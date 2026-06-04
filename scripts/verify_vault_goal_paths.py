#!/usr/bin/env python3
"""Verify Obsidian vault paths needed for Hibi goal conditioning (KAZ-206).

Exits 0 when ``OBSIDIAN_VAULT_ROOT`` exists; prints OK/MISS for allowlisted
``10_projects/<slug>/`` conditioning files. Used in daily-news Actions after
sparse vault checkout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from goals.loader import CONDITIONING_FILES, SUBJECT_ALLOWLIST, VAULT_ROOT_ENV


def main() -> int:
    root = os.environ.get(VAULT_ROOT_ENV)
    if not root:
        print(f"{VAULT_ROOT_ENV} is not set.")
        return 1

    vault = Path(root)
    if not vault.is_dir():
        print(f"Vault root missing: {vault}")
        return 1

    print(f"Vault root: {vault}")
    any_file = False
    for slug in SUBJECT_ALLOWLIST:
        project_dir = vault / "10_projects" / slug
        if not project_dir.is_dir():
            print(f"MISS directory {project_dir}")
            continue
        for filename in CONDITIONING_FILES:
            path = project_dir / filename
            if path.is_file():
                any_file = True
                print(f"OK   {path}")
            else:
                print(f"MISS {path}")

    if not any_file:
        print(
            "WARN: no conditioning files found; goal context may be empty "
            "(check frontmatter status: active on decisions/strategy/status)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
