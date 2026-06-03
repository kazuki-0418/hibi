"""Subject-project conditioning for digest v2 (KAZ-204).

Growth targets are explicit allowlisted folders under ``10_projects/`` —
not ``hibi`` itself. Conditioning uses ``decisions.md``, ``strategy.md``,
``status.md`` via ``goals.loader.read_active_note`` (frontmatter + section
extraction + file mtime ordering). ``daily-log`` is excluded by filename.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from goals.loader import (
    CONDITIONING_FILES,
    OPTIONAL_ENV,
    OVERRIDE_ENV,
    PROJECTS_SUBPATH,
    SUBJECT_ALLOWLIST,
    VAULT_ROOT_ENV,
    read_active_note,
)

CONDITIONING_CHAR_LIMIT: Final[int] = 8000
DISPLAY_NAMES: Final[dict[str, str]] = {
    "monogatari": "Monogatari",
    "roamlore": "RoamLore",
}


@dataclass(frozen=True)
class SubjectProject:
    slug: str
    display_name: str
    conditioning_text: str
    file_count: int


@dataclass(frozen=True)
class SubjectCatalog:
    projects: tuple[SubjectProject, ...]

    @property
    def slugs(self) -> tuple[str, ...]:
        return tuple(p.slug for p in self.projects)

    def conditioning_for(self, slug: str) -> str:
        for project in self.projects:
            if project.slug == slug:
                return project.conditioning_text
        return ""

    def display_name(self, slug: str) -> str:
        return DISPLAY_NAMES.get(slug, slug)


def _optional_enabled() -> bool:
    return os.environ.get(OPTIONAL_ENV) == "1"


def _recency_weight(mtime: float, now: float) -> float:
    """Linear decay: 1.0 today, ~0.5 at 7 days, floor 0.1."""
    age_days = max(0.0, (now - mtime) / 86400.0)
    return max(0.1, 1.0 - age_days / 14.0)


def _load_conditioning(project_dir: Path) -> tuple[str, int]:
    now = datetime.now(timezone.utc).timestamp()
    weighted: list[tuple[float, str, str]] = []
    used = 0
    for filename in CONDITIONING_FILES:
        path = project_dir / filename
        if not path.is_file():
            continue
        used += 1
        body = read_active_note(path)
        if not body:
            continue
        weight = _recency_weight(path.stat().st_mtime, now)
        weighted.append((weight, filename, body))
    weighted.sort(key=lambda row: row[0], reverse=True)

    parts: list[str] = []
    for _weight, filename, body in weighted:
        parts.append(f"## {filename}\n{body}")
    text = "\n\n".join(parts)[:CONDITIONING_CHAR_LIMIT]
    return text, used


def load_subject_catalog() -> SubjectCatalog:
    """Load allowlisted subject projects and their conditioning corpora."""
    override = os.environ.get(OVERRIDE_ENV, "").strip()
    if override:
        demo = SubjectProject(
            slug="monogatari",
            display_name="Monogatari",
            conditioning_text=override[:CONDITIONING_CHAR_LIMIT],
            file_count=1,
        )
        return SubjectCatalog(projects=(demo,))

    optional = _optional_enabled()
    vault_root = os.environ.get(VAULT_ROOT_ENV)
    if not vault_root:
        if optional:
            return SubjectCatalog(projects=())
        raise RuntimeError(
            f"{VAULT_ROOT_ENV} is not set; cannot load subject projects. "
            f"Set {OPTIONAL_ENV}=1 to bypass (tests/CI only)."
        )

    projects_root = Path(vault_root) / PROJECTS_SUBPATH
    if not projects_root.is_dir():
        if optional:
            return SubjectCatalog(projects=())
        raise RuntimeError(f"Projects directory missing: {projects_root}")

    loaded: list[SubjectProject] = []
    for slug in SUBJECT_ALLOWLIST:
        project_dir = projects_root / slug
        if not project_dir.is_dir():
            continue
        text, file_count = _load_conditioning(project_dir)
        loaded.append(
            SubjectProject(
                slug=slug,
                display_name=DISPLAY_NAMES.get(slug, slug),
                conditioning_text=text,
                file_count=file_count,
            )
        )
    return SubjectCatalog(projects=tuple(loaded))
