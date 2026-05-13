"""Neon PostgreSQL への接続・CRUD を提供するモジュール。"""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

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


def save_article(article: dict, edition_id: int) -> str | None:
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
        edition_id: 紐付ける editions.issue_no。`articles.edition_id` は
            migration 005 で NOT NULL になっているので必須。日次の caller は
            `get_or_create_edition_for_today()` で 1 回取得して使い回す想定。
    """
    params = {
        **article,
        "category": article.get("category"),
        "embedding": article.get("embedding"),
        "embedding_model": article.get("embedding_model"),
        "edition_id": edition_id,
    }
    # ON CONFLICT DO UPDATE で no-op update を掛けることで、衝突時も RETURNING
    # が発火する。content_id = EXCLUDED.content_id は元値への no-op。
    with get_conn() as conn:
        row = conn.execute(
            """
            insert into articles
              (source_type, source_name, content_id, title, url, summary, category,
               embedding, embedding_model, edition_id, sent_at)
            values
              (%(source_type)s, %(source_name)s, %(content_id)s,
               %(title)s, %(url)s, %(summary)s, %(category)s,
               %(embedding)s, %(embedding_model)s, %(edition_id)s, now())
            on conflict (content_id) do update
              set content_id = excluded.content_id
            returning id
            """,
            params,
        ).fetchone()
        conn.commit()
        return str(row[0]) if row else None


# ============================================================
# Editions
# ============================================================
def _today_utc():
    """UTC の今日の date。backfill / migration とタイムゾーン整合を取る。"""
    return datetime.now(timezone.utc).date()


def get_or_create_edition_for_today() -> int:
    """今日の `editions` 行を取得。無ければ作る。返り値は issue_no。

    冪等: 同じ日に複数回呼んでも同じ issue_no を返す (editions.date UNIQUE
    に依拠)。`issue_no` は MAX(issue_no) + 1 で採番。

    `articles.edition_id` が NOT NULL の制約 (migration 005) を満たすため、
    `save_article` を呼ぶ前に必ず 1 回呼ぶこと。
    """
    today = _today_utc()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select issue_no from editions where date = %s", (today,))
            row = cur.fetchone()
            if row:
                return int(row[0])
            cur.execute("select coalesce(max(issue_no), 0) + 1 from editions")
            next_no = int(cur.fetchone()[0])
            cur.execute(
                "insert into editions (issue_no, date) values (%s, %s)",
                (next_no, today),
            )
        conn.commit()
        return next_no


def update_edition_sources_scanned(
    issue_no: int, sources_scanned: list[dict]
) -> None:
    """`editions.sources_scanned` を更新する。

    形式は Issue #52 に従う:
        [{"name": str, "kind": "YouTube"|"RSS",
          "fetched_count": int, "error": str (optional)}, ...]

    上書き保存。1 日 1 回 (Stage A 完了直後) 呼ぶ想定。
    """
    with get_conn() as conn:
        conn.execute(
            "update editions set sources_scanned = %s where issue_no = %s",
            (Jsonb(sources_scanned), issue_no),
        )
        conn.commit()


def update_edition_meta(
    issue_no: int, standfirst: str, daily_title: str
) -> None:
    """`editions.standfirst` / `editions.daily_title` を更新する (Issue #53)。

    daily_news.py の Stage D (Claude による edition meta 生成) 完了時に
    1 回呼ぶ想定。失敗時のフォールバック値も呼び出し側で確定済みで
    渡される (= 空文字 / None は入らない想定)。

    上書き保存。冪等。
    """
    with get_conn() as conn:
        conn.execute(
            """
            update editions
               set standfirst = %s,
                   daily_title = %s
             where issue_no = %s
            """,
            (standfirst, daily_title, issue_no),
        )
        conn.commit()


def get_stats_summary() -> dict[str, int]:
    """`stats_summary` VIEW を 1 行読み出す (Issue #54).

    Returns:
        ``{"editions_count": int, "stories_count": int, "sources_count": int}``

    呼び元は web archive masthead の集計表示 (#58)。view 側で 3 列を
    1 行にまとめているので、 read は常に 1 行・1 RTT。
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select editions_count, stories_count, sources_count "
            "from stats_summary"
        )
        row = cur.fetchone()
        if row is None:
            return {"editions_count": 0, "stories_count": 0, "sources_count": 0}
        return {
            "editions_count": int(row[0]),
            "stories_count": int(row[1]),
            "sources_count": int(row[2]),
        }
