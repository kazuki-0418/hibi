"""Thin psycopg-based DB layer for the service.

Kept as module-level functions so tests can monkeypatch them without having
to stand up a real Postgres.
"""

from __future__ import annotations

import logging
from typing import Optional, TypedDict

import psycopg
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)


class Article(TypedDict):
    url: str
    user_id: str


_pool: Optional[ConnectionPool] = None


def init_pool(database_url: str) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = ConnectionPool(conninfo=database_url, min_size=1, max_size=4, open=True)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_article(article_id: str) -> Optional[Article]:
    assert _pool is not None, "db.init_pool() must be called before queries"
    try:
        with _pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "select url, user_id::text from articles where id::text = %s",
                (article_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {"url": row[0], "user_id": row[1]}
    except psycopg.DataError:
        # e.g. article_id is not a valid uuid shape → treat as missing
        return None
    except psycopg.Error:
        # Pool / connection failures (OperationalError, InterfaceError, ...)
        # — typically Neon scale-to-zero cold start. Return None so the click
        # handler can fall back to missing_redirect_url instead of 500-ing.
        log.exception("get_article: db error for article_id=%s", article_id)
        return None


def log_click(
    article_id: str,
    user_id: str,
    user_agent: str,
    ip_hash: str,
) -> None:
    assert _pool is not None, "db.init_pool() must be called before queries"
    with _pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into clicks (article_id, user_id, user_agent, ip_hash)
            values (%s::uuid, %s::uuid, %s, %s)
            """,
            (article_id, user_id, user_agent, ip_hash),
        )
