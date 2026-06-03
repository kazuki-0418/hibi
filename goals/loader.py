"""Load goal focus / conditioning text from Obsidian ``10_projects/`` notes.

Conventions (KAZ-202 / KAZ-204):
- Vault root: ``OBSIDIAN_VAULT_ROOT``.
- Subject allowlist (growth targets): ``monogatari``, ``roamlore`` — not ``hibi``.
- A note is **active** only with YAML frontmatter ``hibi-active: true`` or
  ``status: active`` (case-insensitive). Notes without frontmatter are skipped.
- Section extraction uses **exact** ``##`` heading match (case-insensitive).
- Notes are merged newest-first (mtime desc) before the char cap.
- Abandoned path segments are skipped: ``archive``, ``done``, ``abandoned``, ``.trash``.

Tests may set ``HIBI_GOALS_OPTIONAL=1`` or ``HIBI_GOAL_CONTEXT_OVERRIDE``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

VAULT_ROOT_ENV: Final[str] = "OBSIDIAN_VAULT_ROOT"
OPTIONAL_ENV: Final[str] = "HIBI_GOALS_OPTIONAL"
OVERRIDE_ENV: Final[str] = "HIBI_GOAL_CONTEXT_OVERRIDE"
PROJECTS_SUBPATH: Final[str] = "10_projects"
GOAL_FOCUS_CHAR_LIMIT: Final[int] = 6000

SUBJECT_ALLOWLIST: Final[tuple[str, ...]] = ("monogatari", "roamlore")
CONDITIONING_FILES: Final[tuple[str, ...]] = (
    "decisions.md",
    "strategy.md",
    "status.md",
)

_EXCLUDED_PATH_PARTS: Final[frozenset[str]] = frozenset(
    {"archive", "done", "abandoned", ".trash", "_templates"}
)
_ACTIVE_FM_KEYS: Final[tuple[str, ...]] = ("hibi-active", "status")
_ACTIVE_FM_VALUES: Final[frozenset[str]] = frozenset({"active", "true", "yes"})
_SECTION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "goal",
        "ゴール",
        "focus",
        "焦点",
        "進捗",
        "決定",
        "progress",
        "decision",
        "戦略",
        "strategy",
        "vision",
        "ビジョン",
        "positioning",
        "ポジショニング",
        "現状",
        "現在のフェーズ",
        "status",
    }
)
_FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class GoalFocus:
    """Minimal text bundle passed to embedding / summarization prompts."""

    text: str
    project_slugs: tuple[str, ...]


def _optional_enabled() -> bool:
    return os.environ.get(OPTIONAL_ENV) == "1"


def _frontmatter_active(fm: str) -> bool:
    for line in fm.splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip().lower()
        if key not in _ACTIVE_FM_KEYS:
            continue
        value = raw.strip().strip("\"'").lower()
        if value in _ACTIVE_FM_VALUES:
            return True
    return False


def _extract_focus_sections(body: str) -> str:
    """Keep only goal-relevant ## sections; drop the rest of the note."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return body.strip()[:2000]

    parts: list[str] = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip().lower()
        if title not in _SECTION_NAMES:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        if chunk:
            parts.append(f"## {match.group(1).strip()}\n{chunk}")
    return "\n\n".join(parts)


def read_active_note(path: Path) -> str:
    """Return extracted focus text for an active note, or empty if inactive."""
    raw = path.read_text(encoding="utf-8")
    body = raw
    fm_match = _FRONTMATTER_RE.match(raw)
    if fm_match:
        if not _frontmatter_active(fm_match.group(1)):
            return ""
        body = raw[fm_match.end() :]
    elif not _optional_enabled():
        return ""

    return _extract_focus_sections(body)


def _path_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_PATH_PARTS for part in path.parts)


def _notes_newest_first(project_dir: Path) -> list[str]:
    """Collect active note excerpts sorted by mtime descending."""
    dated: list[tuple[float, str]] = []
    for md_path in project_dir.rglob("*.md"):
        if _path_excluded(md_path):
            continue
        focus = read_active_note(md_path)
        if focus:
            dated.append((md_path.stat().st_mtime, focus))
    dated.sort(key=lambda row: row[0], reverse=True)
    return [text for _, text in dated]


def load_goal_focus() -> GoalFocus:
    """Load capped goal focus from allowlisted active project notes."""
    override = os.environ.get(OVERRIDE_ENV, "").strip()
    if override:
        return GoalFocus(text=override[:GOAL_FOCUS_CHAR_LIMIT], project_slugs=("override",))

    optional = _optional_enabled()
    vault_root = os.environ.get(VAULT_ROOT_ENV)
    if not vault_root:
        if optional:
            return GoalFocus(text="", project_slugs=())
        raise RuntimeError(
            f"{VAULT_ROOT_ENV} is not set; cannot load goal context. "
            f"Set {OPTIONAL_ENV}=1 to bypass (tests/CI only)."
        )

    projects_root = Path(vault_root) / PROJECTS_SUBPATH
    if not projects_root.is_dir():
        if optional:
            return GoalFocus(text="", project_slugs=())
        raise RuntimeError(f"Projects directory missing: {projects_root}")

    chunks: list[str] = []
    slugs: list[str] = []
    for slug in SUBJECT_ALLOWLIST:
        project_dir = projects_root / slug
        if not project_dir.is_dir():
            continue
        project_parts = _notes_newest_first(project_dir)
        if not project_parts:
            continue
        slugs.append(slug)
        combined = "\n\n".join(project_parts)
        chunks.append(f"# Project: {slug}\n{combined}")

    text = "\n\n".join(chunks)[:GOAL_FOCUS_CHAR_LIMIT]
    return GoalFocus(text=text, project_slugs=tuple(slugs))
