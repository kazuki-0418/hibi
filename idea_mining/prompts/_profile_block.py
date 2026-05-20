"""Prompt-side helper: return the profile block to paste at prompt head.

下流 prompt (#138 Ideator / #139 Critic) はこの関数だけを import すれば
profile を取り込める。loader 直呼びを避け、将来 wrap (例: section header
の付与) を入れる余地を残す。
"""
from __future__ import annotations

from idea_mining.profile_loader import load as _load_profile


def profile_block() -> str:
    """Return the profile Markdown block to paste at the head of a prompt.

    Thin pass-through over `profile_loader.load()`; semantics (fails-closed,
    `HIBI_VAULT_OPTIONAL=1` escape) follow the loader exactly.
    """
    return _load_profile()
