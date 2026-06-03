"""Per-project embedding centroids with on-disk cache (KAZ-204)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Final

from goals.subjects import SubjectCatalog, SubjectProject

CACHE_DIR_ENV: Final[str] = "HIBI_GOAL_CACHE_DIR"
CACHE_FILENAME: Final[str] = "goal_centroid_cache.json"


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _cache_path() -> Path | None:
    explicit = os.environ.get(CACHE_DIR_ENV)
    if explicit:
        return Path(explicit) / CACHE_FILENAME
    vault = os.environ.get("OBSIDIAN_VAULT_ROOT")
    if vault:
        return Path(vault) / ".hibi" / CACHE_FILENAME
    return None


def _read_cache() -> dict[str, dict[str, object]]:
    path = _cache_path()
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _write_cache(data: dict[str, dict[str, object]]) -> None:
    path = _cache_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def embed_subject_centroids(
    openai_client,
    catalog: SubjectCatalog,
    *,
    embed_batch,
    embedding_model: str,
) -> dict[str, list[float]]:
    """Return per-slug centroids; reuse cache when conditioning fingerprint matches."""
    if openai_client is None or not catalog.projects:
        return {}

    cache = _read_cache()
    out: dict[str, list[float]] = {}
    to_embed: list[SubjectProject] = []
    texts: list[str] = []

    for project in catalog.projects:
        if not project.conditioning_text.strip():
            continue
        fp = _fingerprint(project.conditioning_text)
        entry = cache.get(project.slug)
        if (
            isinstance(entry, dict)
            and entry.get("fingerprint") == fp
            and isinstance(entry.get("embedding"), list)
        ):
            out[project.slug] = [float(x) for x in entry["embedding"]]
            continue
        to_embed.append(project)
        texts.append(project.conditioning_text)

    if to_embed:
        vectors = embed_batch(openai_client, texts)
        for project, vec in zip(to_embed, vectors, strict=False):
            if vec is None:
                continue
            fp = _fingerprint(project.conditioning_text)
            out[project.slug] = vec
            cache[project.slug] = {
                "fingerprint": fp,
                "embedding": vec,
                "model": embedding_model,
            }

    _write_cache(cache)
    return out
