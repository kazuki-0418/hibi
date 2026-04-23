"""Neon PostgreSQL への接続・CRUD を提供するモジュール。"""

import os
import sys
from contextlib import contextmanager

import psycopg

try:
    from pgvector.psycopg import register_vector

    _HAS_PGVECTOR = True
except ImportError:  # backfill/embedding 機能を使わない pip 構成でも import だけは通す
    _HAS_PGVECTOR = False


def _get_database_url() -> str:
    """DATABASE_URL を取得。未設定なら即 fail。"""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return url


@contextmanager
def get_conn():
    """psycopg 接続の context manager。pgvector が入っていれば vector 型を有効化。"""
    with psycopg.connect(_get_database_url()) as conn:
        if _HAS_PGVECTOR:
            try:
                register_vector(conn)
            except Exception:
                # vector 拡張が未作成の環境でも articles CRUD は動かせるように
                pass
        yield conn


def is_already_sent(content_id: str) -> bool:
    """同じ content_id が既に articles に存在するか。"""
    with get_conn() as conn:
        row = conn.execute(
            "select 1 from articles where content_id = %s limit 1",
            (content_id,),
        ).fetchone()
        return row is not None


def save_article(article: dict) -> str | None:
    """articles テーブルに1件保存し、その行の id (uuid, str) を返す。

    content_id が既存の場合も既存行の id を返す。DB 接続不可などで保存できなか
    ったときは None。呼び出し側はメール内のクリック追跡 URL 生成に id を使う。

    Args:
        article: 以下のキーを持つ dict
            - source_type: 'youtube' | 'rss'
            - source_name: str
            - content_id: str (unique)
            - title: str
            - url: str
            - summary: str | None
            - category: str | None  (optional; source_metrics_30d の GROUP BY に使う)
            - embedding: list[float] | None  (optional; vector(1536))
            - embedding_model: str | None    (optional; どの model で埋め込んだか)
    """
    params = {
        **article,
        "category": article.get("category"),
        "embedding": article.get("embedding"),
        "embedding_model": article.get("embedding_model"),
    }
    # ON CONFLICT DO UPDATE で no-op update を掛けることで、衝突時も RETURNING
    # が発火する。content_id = EXCLUDED.content_id は元値への no-op。
    with get_conn() as conn:
        row = conn.execute(
            """
            insert into articles
              (source_type, source_name, content_id, title, url, summary, category,
               embedding, embedding_model, sent_at)
            values
              (%(source_type)s, %(source_name)s, %(content_id)s,
               %(title)s, %(url)s, %(summary)s, %(category)s,
               %(embedding)s, %(embedding_model)s, now())
            on conflict (content_id) do update
              set content_id = excluded.content_id
            returning id
            """,
            params,
        ).fetchone()
        conn.commit()
        return str(row[0]) if row else None
