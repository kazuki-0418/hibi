"""Ranking helpers: click centroid, goal centroid blend, cosine similarity."""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence


def compute_interest_centroid(conn, user_id: str, days: int = 30) -> Optional[Any]:
    """Return the average embedding of the user's clicks in the last N days.

    Returns None when the user has no clicks in the window, or when none of
    the clicked articles have embeddings yet (e.g. before backfill runs).
    """
    row = conn.execute(
        """
        SELECT AVG(a.embedding)::vector(1536)
        FROM clicks c
        JOIN articles a ON a.id = c.article_id
        WHERE c.user_id   = %s::uuid
          AND c.clicked_at > NOW() - (%s || ' days')::interval
          AND a.embedding IS NOT NULL
        """,
        (user_id, str(days)),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def count_recent_clicks(conn, user_id: str, days: int = 30) -> int:
    """Count clicks by this user in the last N days (used for cold-start gating)."""
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM clicks
        WHERE user_id    = %s::uuid
          AND clicked_at > NOW() - (%s || ' days')::interval
        """,
        (user_id, str(days)),
    ).fetchone()
    return int(row[0]) if row else 0


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two 1-D vectors. Zero-safe (fails open to sim=0)."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def blend_centroids(
    goal: Sequence[float],
    click: Sequence[float],
    click_weight: float,
) -> list[float]:
    """Element-wise blend; ``click_weight`` in [0, 1] weights the click centroid."""
    w = max(0.0, min(1.0, click_weight))
    return [float(g) * (1.0 - w) + float(c) * w for g, c in zip(goal, click, strict=False)]
