"""editions テーブル + 紐付く articles を web/src/content/editions/*.json に dump する。

使い方:
    python scripts/dump_editions_to_json.py --dry-run   # 件数のみ
    python scripts/dump_editions_to_json.py --apply     # 実書き出し

Astro Content Collection (web/src/content/config.ts) が `editions` を読み込み、
edition page (`web/src/pages/edition/[issue_no].astro`) が build 時に各号の
HTML を生成する。Astro 側から直接 DB を叩かない (build-time data 原則)。

ファイル名は zero-padded 4 桁 (`0001.json`) で sort 安定化。出力先は **上書き
保存** (idempotent)。古い edition が DB から消えても削除されないので、その場合
は手で `rm web/src/content/editions/<old>.json` する。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "web" / "src" / "content" / "editions"


def _isoformat_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _load_editions(cur: psycopg.Cursor) -> list[dict]:
    cur.execute(
        """
        select issue_no, date, standfirst, daily_title, sources_scanned, generated_at
        from editions
        order by issue_no asc
        """
    )
    cols = [c.name for c in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_articles_for(cur: psycopg.Cursor, edition_id: int) -> list[dict]:
    cur.execute(
        """
        select title, url, summary, category, source_name as source, source_type
        from articles
        where edition_id = %s
        order by created_at asc
        """,
        (edition_id,),
    )
    cols = [c.name for c in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _to_json_payload(edition: dict, articles: list[dict]) -> dict:
    return {
        "issue_no": int(edition["issue_no"]),
        "date": _isoformat_date(edition["date"]),
        "standfirst": edition.get("standfirst"),
        "daily_title": edition.get("daily_title"),
        "sources_scanned": edition.get("sources_scanned"),
        "articles": articles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="件数のみ表示。ファイル書き出しなし")
    group.add_argument("--apply", action="store_true", help="web/src/content/editions/ に書き出す")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        return 1

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        editions = _load_editions(cur)

        if not editions:
            print("⚠️  editions table is empty.")
            return 0

        payloads: list[tuple[int, dict]] = []
        for ed in editions:
            arts = _load_articles_for(cur, ed["issue_no"])
            payloads.append((ed["issue_no"], _to_json_payload(ed, arts)))

    print(f"Editions:    {len(payloads)}")
    print(f"First / last: {payloads[0][0]} / {payloads[-1][0]}")
    print(f"Output dir:  {OUTPUT_DIR}")

    if args.dry_run:
        sample = payloads[0][1]
        print("\nSample (first edition):")
        print(f"  issue_no={sample['issue_no']}  date={sample['date']}  articles={len(sample['articles'])}")
        if sample.get("sources_scanned"):
            print(f"  sources_scanned: {len(sample['sources_scanned'])} entries")
        else:
            print("  sources_scanned: null (pre-#52 edition or no data yet)")
        print("\nRun with --apply to write JSON files.")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for issue_no, payload in payloads:
        path = OUTPUT_DIR / f"{issue_no:04d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        written += 1
    print(f"\n✅ Wrote {written} JSON files to {OUTPUT_DIR}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
