"""既存 articles 行に embedding を backfill する。

使い方:
    python scripts/backfill_embeddings.py --dry-run   # 件数・トークン・料金推定のみ
    python scripts/backfill_embeddings.py --apply     # 実際に埋め込み

title + summary を入力に `text-embedding-3-small` (1536 dim) で埋めて
`articles.embedding` と `articles.embedding_model` に書き込む。
`embedding IS NULL` な行だけを対象に、BATCH 件ずつ OpenAI に投げる。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()

MODEL = "text-embedding-3-small"
BATCH = 50
# 2026-04 時点の text-embedding-3-small の料金。README で定期的に見直す。
USD_PER_1M_TOKENS = 0.02
# ざっくり "1 token ≒ 4 chars" で概算（英語寄り。日本語は混在するので誤差 +20% 程度）
CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _load_rows(cur: psycopg.Cursor) -> list[tuple[str, str, str]]:
    cur.execute(
        """
        select id::text, coalesce(title, ''), coalesce(summary, '')
        from articles
        where embedding is null
        order by created_at nulls first
        """
    )
    return cur.fetchall()


def _batched(rows, size):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def dry_run(rows: list[tuple[str, str, str]]) -> None:
    total_tokens = sum(_estimate_tokens(f"{t}\n\n{s}") for _id, t, s in rows)
    cost = total_tokens / 1_000_000 * USD_PER_1M_TOKENS
    print(f"Rows needing embedding: {len(rows)}")
    print(f"Estimated tokens:       {total_tokens:,}")
    print(f"Estimated cost:         ${cost:.4f}  (model={MODEL})")
    print("\nRun with --apply to actually embed.")


def apply(rows: list[tuple[str, str, str]], conn: psycopg.Connection) -> None:
    from openai import OpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI()

    done = 0
    for batch in _batched(rows, BATCH):
        texts = [f"{t}\n\n{s}" for _id, t, s in batch]
        resp = client.embeddings.create(model=MODEL, input=texts)
        vectors = [d.embedding for d in resp.data]

        with conn.cursor() as cur:
            for (row_id, _, _), vec in zip(batch, vectors):
                cur.execute(
                    "update articles set embedding = %s, embedding_model = %s where id = %s::uuid",
                    (vec, MODEL, row_id),
                )
        conn.commit()
        done += len(batch)
        print(f"  {done}/{len(rows)}")
        # OpenAI tier 1 の rate limit は 3000 RPM / 1M TPM。50件/秒以下で余裕。
        time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="count + cost estimate only")
    group.add_argument("--apply", action="store_true", help="actually run embeddings")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        return 1

    with psycopg.connect(db_url) as conn:
        try:
            register_vector(conn)
        except Exception as e:
            print(f"ERROR: pgvector adapter not registerable: {e}", file=sys.stderr)
            print("Run migrations/003_embedding.sql first.", file=sys.stderr)
            return 1

        with conn.cursor() as cur:
            rows = _load_rows(cur)

        if not rows:
            print("✅ Nothing to backfill — all articles already have embeddings.")
            return 0

        if args.dry_run:
            dry_run(rows)
            return 0

        apply(rows, conn)

    print("\n✅ Backfill complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
