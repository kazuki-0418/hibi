"""Neon PostgreSQL への接続・CRUD を提供するモジュール。"""

import os
import sys
from contextlib import contextmanager

import psycopg


def _get_database_url() -> str:
    """DATABASE_URL を取得。未設定なら即 fail。"""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return url


@contextmanager
def get_conn():
    """psycopg 接続の context manager。"""
    with psycopg.connect(_get_database_url()) as conn:
        yield conn


def is_already_sent(content_id: str) -> bool:
    """同じ content_id が既に articles に存在するか。"""
    with get_conn() as conn:
        row = conn.execute(
            "select 1 from articles where content_id = %s limit 1",
            (content_id,),
        ).fetchone()
        return row is not None


def save_article(article: dict) -> None:
    """articles テーブルに1件保存。content_id 衝突時は何もしない。

    Args:
        article: 以下のキーを持つ dict
            - source_type: 'youtube' | 'rss'
            - source_name: str
            - content_id: str (unique)
            - title: str
            - url: str
            - summary: str | None
    """
    with get_conn() as conn:
        conn.execute(
            """
            insert into articles
              (source_type, source_name, content_id, title, url, summary, sent_at)
            values
              (%(source_type)s, %(source_name)s, %(content_id)s,
               %(title)s, %(url)s, %(summary)s, now())
            on conflict (content_id) do nothing
            """,
            article,
        )
        conn.commit()
