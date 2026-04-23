"""migrations/002_phase3_schema.sql の適用結果を確認する smoke test。

DATABASE_URL に接続し、
  - articles.user_id / articles.category 列の存在
  - clicks テーブル + FK
  - source_metrics_30d VIEW のクエリ可能性
を確認する。本番パイプラインからは呼ばれない。

使い方:
    python scripts/smoke_phase3_schema.py
"""

from __future__ import annotations

import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
    sys.exit(1)


CHECKS: list[tuple[str, str]] = [
    (
        "articles.user_id exists and is NOT NULL",
        """
        select is_nullable
        from information_schema.columns
        where table_name = 'articles' and column_name = 'user_id'
        """,
    ),
    (
        "articles.category column exists",
        """
        select 1
        from information_schema.columns
        where table_name = 'articles' and column_name = 'category'
        """,
    ),
    (
        "clicks table exists",
        """
        select 1 from information_schema.tables where table_name = 'clicks'
        """,
    ),
    (
        "clicks.article_id FK references articles(id)",
        """
        select 1
        from information_schema.referential_constraints rc
        join information_schema.key_column_usage kcu
          on rc.constraint_name = kcu.constraint_name
        where kcu.table_name  = 'clicks'
          and kcu.column_name = 'article_id'
        """,
    ),
    (
        "source_metrics_30d view is queryable",
        "select count(*) from source_metrics_30d",
    ),
]


def main() -> int:
    failures: list[str] = []
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            for label, sql in CHECKS:
                cur.execute(sql)
                row = cur.fetchone()
                if row is None:
                    failures.append(label)
                    print(f"❌ {label}")
                    continue

                if label.startswith("articles.user_id"):
                    # is_nullable が 'NO' であること
                    if row[0] != "NO":
                        failures.append(label)
                        print(f"❌ {label} — is_nullable={row[0]!r}")
                        continue

                print(f"✅ {label}")
    except Exception as e:
        print(f"❌ connection or query failed: {e}", file=sys.stderr)
        return 1

    if failures:
        print(f"\n❌ {len(failures)} check(s) failed", file=sys.stderr)
        return 1

    print("\n✅ Phase 3 schema smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
