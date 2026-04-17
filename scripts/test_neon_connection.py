"""Neon PostgreSQL への接続を確認する最小スクリプト。

実装前の疎通確認用。本番パイプラインからは呼ばれない。
"""

import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
    sys.exit(1)

try:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select version();")
            version = cur.fetchone()[0]
            print(f"✅ PostgreSQL version: {version}")

            cur.execute("select count(*) from articles;")
            count = cur.fetchone()[0]
            print(f"✅ articles count: {count}")

            cur.execute(
                "select extname, extversion from pg_extension where extname = 'vector';"
            )
            row = cur.fetchone()
            if row:
                print(f"✅ pgvector: {row[0]} v{row[1]}")
            else:
                print("⚠️ pgvector extension not found")

    print("\n✅ Neon connection test passed.")
except Exception as e:
    print(f"❌ Connection failed: {e}", file=sys.stderr)
    sys.exit(1)
