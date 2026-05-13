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


class ArticleWithEdition(TypedDict):
    url: str
    user_id: str
    # issue_no of the edition this article belongs to. None when the article
    # has no edition (orphan rows from before backfill, or FK pointing at a
    # missing edition row). Caller must fall back to missing_redirect_url.
    issue_no: Optional[int]
    # 1-indexed position within the edition, ordered by articles.created_at.
    # None when the article cannot be located in an edition.
    position_in_edition: Optional[int]


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


def get_article_with_edition(article_id: str) -> Optional[ArticleWithEdition]:
    """Like get_article(), but also returns the edition issue_no and the
    1-indexed position of this article within its edition (ordered by
    created_at).

    Used by /r/{id}?to=edition to redirect into the public web archive.
    On any psycopg error (cold start, malformed UUID, missing edition row)
    returns None so the caller can fall back to missing_redirect_url —
    the click handler must not 500 on an analytics endpoint.
    """
    assert _pool is not None, "db.init_pool() must be called before queries"
    try:
        with _pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                with art as (
                    select id, url, user_id::text as user_id,
                           edition_id, created_at
                    from articles
                    where id::text = %s
                ),
                pos as (
                    select count(*) + 1 as position_in_edition
                    from articles a2
                    where a2.edition_id = (select edition_id from art)
                      and a2.created_at < (select created_at from art)
                ),
                ed as (
                    select e.issue_no
                    from editions e
                    where e.issue_no = (select edition_id from art)
                )
                select art.url, art.user_id, ed.issue_no, pos.position_in_edition
                from art
                left join ed on true
                left join pos on true
                """,
                (article_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "url": row[0],
                "user_id": row[1],
                "issue_no": row[2],
                "position_in_edition": row[3],
            }
    except psycopg.DataError:
        return None
    except psycopg.Error:
        log.exception(
            "get_article_with_edition: db error for article_id=%s", article_id
        )
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
