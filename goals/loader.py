"""Load minimal goal focus text from Obsidian ``10_projects/`` active notes.

Active-project convention (KAZ-202):
- Vault root: ``OBSIDIAN_VAULT_ROOT`` (same as idea-mining).
- Scan ``10_projects/<project>/`` — one directory depth under ``10_projects/``.
- A project is **active** when any ``*.md`` in that folder has YAML frontmatter
  with ``hibi-active: true`` or ``status: active`` (case-insensitive).
- Abandoned paths are skipped: ``archive``, ``done``, ``abandoned``, ``.trash``.
- Only these sections are extracted (heading match, case-insensitive):
  Goal / ゴール / Focus / 焦点 / 進捗 / 決定 / Progress / Decision.
- Concatenated focus text is capped at ``GOAL_FOCUS_CHAR_LIMIT`` for API privacy.

Tests may set ``HIBI_GOALS_OPTIONAL=1`` (empty focus, no error) or
``HIBI_GOAL_CONTEXT_OVERRIDE`` (synthetic profile for demos).
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


def _note_focus(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    body = raw
    fm_match = _FRONTMATTER_RE.match(raw)
    if fm_match:
        if not _frontmatter_active(fm_match.group(1)):
            return ""
        body = raw[fm_match.end() :]
    elif not _optional_enabled():
        # Without frontmatter, non-optional runs ignore the file (not marked active).
        return ""

    return _extract_focus_sections(body)


def _path_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_PATH_PARTS for part in path.parts)


def load_goal_focus() -> GoalFocus:
    """Load capped goal focus text from active project notes under ``10_projects/``."""
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
    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        slug = project_dir.name
        project_parts: list[str] = []
        for md_path in sorted(project_dir.rglob("*.md")):
            if _path_excluded(md_path):
                continue
            focus = _note_focus(md_path)
            if focus:
                project_parts.append(focus)
        if not project_parts:
            continue
        slugs.append(slug)
        combined = "\n\n".join(project_parts)
        chunks.append(f"# Project: {slug}\n{combined}")

    text = "\n\n".join(chunks)[:GOAL_FOCUS_CHAR_LIMIT]
    return GoalFocus(text=text, project_slugs=tuple(slugs))
