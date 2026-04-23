"""Click-history-driven similarity ranking for daily_news.py.

Stays deliberately simple: a centroid of recently-clicked article embeddings
is the "interest profile", and candidates are ranked by cosine similarity to
that centroid plus a jitter term. Jitter keeps the recommendation from
collapsing into an echo chamber when the centroid stabilises.

Cold-start + interpolation logic lives in daily_news.rank_candidates; the
helpers here are pure enough to reason about in isolation.
"""

from __future__ import annotations

import math
from typing import Any, Optional


def compute_interest_centroid(conn, user_id: str, days: int = 30) -> Optional[Any]:
    """Return the average embedding of the user's clicks in the last N days.

    Returns None when the user has no clicks in the window, or when none of
    the clicked articles have embeddings yet (e.g. before backfill runs).
    The return value is whatever pgvector.psycopg gives us — typically a
    numpy array when register_vector() has been called on the connection.
    Indexing / len() work the same, and cosine_similarity accepts both.
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


def cosine_similarity(a, b) -> float:
    """Cosine similarity of two 1-D vectors (list/tuple/ndarray). Zero-safe."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
