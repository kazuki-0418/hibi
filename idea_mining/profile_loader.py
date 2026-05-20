"""Vault `profile/` loader.

`${OBSIDIAN_VAULT_ROOT}/10_projects/hibi/idea-mining/profile/` 配下の
`user-constraints.md` と `negative-examples.md` を Markdown 全文のまま結合し、
prompt 先頭に貼付するための 1 つの文字列として返す。

下流 (#138 Ideator / #139 Critic) は profile なしで動かしてはならないため、
vault 未マウントや profile ファイル欠落は `RuntimeError` で fails-closed に
する。テスト用 escape として `HIBI_VAULT_OPTIONAL=1` のときだけ空文字列を
返し RuntimeError を抑制する。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Final

VAULT_ROOT_ENV: Final[str] = "OBSIDIAN_VAULT_ROOT"
OPTIONAL_ENV: Final[str] = "HIBI_VAULT_OPTIONAL"
PROFILE_SUBPATH: Final[str] = "10_projects/hibi/idea-mining/profile"
PROFILE_FILES: Final[tuple[str, ...]] = (
    "user-constraints.md",
    "negative-examples.md",
)


def _optional_enabled() -> bool:
    return os.environ.get(OPTIONAL_ENV) == "1"


def load() -> str:
    """Return the concatenated profile Markdown as one prompt block.

    Concatenates `user-constraints.md` and `negative-examples.md` from
    the vault `profile/` directory in fixed order, separated by a blank
    line. No front-matter parsing or section extraction is performed.

    Raises:
        RuntimeError: When `OBSIDIAN_VAULT_ROOT` is unset, or when any
            of the required `profile/*.md` files is missing. Set
            `HIBI_VAULT_OPTIONAL=1` to suppress and return `""` instead.
    """
    optional = _optional_enabled()
    vault_root = os.environ.get(VAULT_ROOT_ENV)

    if not vault_root:
        if optional:
            return ""
        raise RuntimeError(
            f"{VAULT_ROOT_ENV} is not set; cannot load profile/. "
            f"Point {VAULT_ROOT_ENV} at the Obsidian vault clone, or "
            f"set {OPTIONAL_ENV}=1 to bypass (tests only)."
        )

    profile_dir = Path(vault_root) / PROFILE_SUBPATH
    parts: list[str] = []
    for filename in PROFILE_FILES:
        path = profile_dir / filename
        if not path.is_file():
            if optional:
                return ""
            raise RuntimeError(
                f"Profile file missing: {path}. Expected "
                f"{PROFILE_SUBPATH}/{filename} under {VAULT_ROOT_ENV}."
            )
        parts.append(path.read_text(encoding="utf-8"))

    return "\n\n".join(parts)
