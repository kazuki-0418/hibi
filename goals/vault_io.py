"""Vault-side capture + idea-mining inbox writes (KAZ-204)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from goals.loader import OPTIONAL_ENV, VAULT_ROOT_ENV

CAPTURE_SUBPATH: Final[str] = "30_raw/hibi/capture"
INBOX_SUBPATH: Final[str] = "30_raw/hibi/inbox"
NOVELTY_INBOX_MAX_PER_DAY: Final[int] = 1


def _vault_root() -> Path | None:
    root = os.environ.get(VAULT_ROOT_ENV)
    if root:
        return Path(root)
    if os.environ.get(OPTIONAL_ENV) == "1":
        return None
    return None


def _slugify(text: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (cleaned or "item")[:max_len]


def write_raw_capture(
    *,
    title: str,
    url: str,
    target_project: str | None,
    summary: str | None,
    goal_note: str | None,
) -> Path | None:
    """Write a raw capture stub under ``30_raw/hibi/capture/`` (not decisions.md)."""
    root = _vault_root()
    if root is None:
        return None

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = root / CAPTURE_SUBPATH
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}-{_slugify(title)}.md"
    lines = [
        "---",
        "source: hibi-digest",
        f"project: {target_project or 'unassigned'}",
        f"captured_at: {datetime.now(timezone.utc).isoformat()}",
        "---",
        "",
        f"# {title}",
        "",
        f"URL: {url}",
        "",
    ]
    if summary:
        lines.extend(["## Digest summary", summary, ""])
    if goal_note:
        lines.extend(["## Application note", goal_note, ""])
    lines.append("## Notes\n\n(manual follow-up)")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_novelty_inbox_item(
    *,
    title: str,
    url: str,
    reason: str,
) -> Path | None:
    """Route low-centroid-match articles to the idea-mining Obsidian inbox (max 1/day)."""
    root = _vault_root()
    if root is None:
        return None

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = root / INBOX_SUBPATH
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = list(out_dir.glob(f"{day}-*.md"))
    if len(existing) >= NOVELTY_INBOX_MAX_PER_DAY:
        return None

    path = out_dir / f"{day}-{_slugify(title)}.md"
    body = (
        "---\n"
        "source: hibi-novelty\n"
        f"date: {day}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"URL: {url}\n\n"
        f"Routed because: {reason}\n\n"
        "Review in idea-mining workflow; do not merge into decisions.md automatically.\n"
    )
    path.write_text(body, encoding="utf-8")
    return path
