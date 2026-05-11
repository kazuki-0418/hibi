"""既存 articles 行に edition_id を遡及採番する。

使い方:
    python scripts/backfill_editions.py --dry-run   # 件数 + 採番プレビューのみ
    python scripts/backfill_editions.py --apply     # 実 backfill

仕様 (Issue #51 PR2):
- `articles` の `created_at::date` ごとに 1 edition を生成
- `editions.issue_no` は **date 昇順で 1 から連番**
- 既に `editions` に登録済みの date は再採番しない (= 冪等)
- 既存の edition の issue_no が「date 昇順 + 1 から連番」と矛盾する
  場合は **error 終了**。番号体系を破壊しないため、人間判断を待つ
- `articles.edition_id` が既に埋まっている行は触らない

依存:
- migrations/004_editions.sql が適用済 (`editions` テーブル + `articles.edition_id` 存在)

PR3 (NOT NULL 化) はこのスクリプトが全件 backfill 完了したことを
確認後に別 migration として実施する想定。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import psycopg
from dotenv import load_dotenv

load_dotenv()


def _load_article_dates(cur: psycopg.Cursor) -> list[date]:
    """edition_id がまだ未設定な articles の日付一覧 (昇順、重複排除)。"""
    cur.execute(
        """
        select distinct created_at::date as d
        from articles
        where edition_id is null
        order by d asc
        """
    )
    return [r[0] for r in cur.fetchall()]


def _load_existing_editions(cur: psycopg.Cursor) -> dict[date, int]:
    """既に登録済みの editions を {date: issue_no} で返す。"""
    cur.execute("select date, issue_no from editions order by issue_no asc")
    return {row[0]: row[1] for row in cur.fetchall()}


def _validate_existing_order(existing: dict[date, int]) -> None:
    """既存 editions が date 昇順かつ 1..N の連番であることを確認。

    一致しない場合は番号体系を勝手に壊さないため error で抜ける。
    """
    if not existing:
        return
    items = sorted(existing.items(), key=lambda kv: kv[1])
    for expected, (_dt, actual) in enumerate(items, start=1):
        if expected != actual:
            raise ValueError(
                f"editions の issue_no が連番でない (expected={expected}, actual={actual} "
                f"for date={_dt}). backfill が安全に拡張できないので中断。"
            )
    dates_in_order = [dt for dt, _ in items]
    if dates_in_order != sorted(dates_in_order):
        raise ValueError(
            f"既存 editions が date 昇順でない: {dates_in_order}. 番号体系を再構築してから再実行。"
        )


def _plan(article_dates: list[date], existing: dict[date, int]) -> list[tuple[int, date, bool]]:
    """date ごとに (issue_no, date, is_new) を返す。

    既存日付は既存 issue_no を再利用。新規日付は MAX(issue_no)+1 から順に。
    返り値は新規・既存両方を含む。
    """
    next_no = max(existing.values(), default=0) + 1
    plan: list[tuple[int, date, bool]] = []
    for dt in article_dates:
        if dt in existing:
            plan.append((existing[dt], dt, False))
        else:
            plan.append((next_no, dt, True))
            next_no += 1
    return plan


def dry_run(plan: list[tuple[int, date, bool]], n_articles_per_date: dict[date, int]) -> None:
    new_dates = [(no, dt) for no, dt, is_new in plan if is_new]
    existing_dates = [(no, dt) for no, dt, is_new in plan if not is_new]
    total_articles = sum(n_articles_per_date.values())

    print(f"Articles needing edition_id: {total_articles}")
    print(f"Distinct dates:              {len(plan)}")
    print(f"  - new editions to insert:  {len(new_dates)}")
    print(f"  - existing editions reused: {len(existing_dates)}")
    if new_dates:
        first_no, first_dt = new_dates[0]
        last_no, last_dt = new_dates[-1]
        print(f"  - new issue_no range:       {first_no}..{last_no} ({first_dt}..{last_dt})")
    print()
    print("Sample (first 5 new editions):")
    for no, dt in new_dates[:5]:
        n = n_articles_per_date.get(dt, 0)
        print(f"  issue_no={no:>4}  date={dt}  articles={n}")
    print("\nRun with --apply to write to DB.")


def _count_articles_per_date(cur: psycopg.Cursor, dates: list[date]) -> dict[date, int]:
    if not dates:
        return {}
    cur.execute(
        """
        select created_at::date as d, count(*) as n
        from articles
        where edition_id is null and created_at::date = any(%s)
        group by d
        """,
        (dates,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def apply(plan: list[tuple[int, date, bool]], conn: psycopg.Connection) -> None:
    """plan に従い editions を埋め、articles.edition_id を採番する。"""
    inserted = 0
    updated_total = 0
    with conn.cursor() as cur:
        for issue_no, dt, is_new in plan:
            if is_new:
                # editions に新規行を挿入。冪等のため ON CONFLICT は date UNIQUE で
                # 弾く (理論上ここに来た時点で date は新しいはずだが念のため)。
                cur.execute(
                    "insert into editions (issue_no, date) values (%s, %s) on conflict (date) do nothing",
                    (issue_no, dt),
                )
                if cur.rowcount > 0:
                    inserted += 1
            # 該当 date の edition_id をまとめて埋める。
            cur.execute(
                "update articles set edition_id = %s where edition_id is null and created_at::date = %s",
                (issue_no, dt),
            )
            updated_total += cur.rowcount or 0
    conn.commit()
    print(f"  inserted editions:        {inserted}")
    print(f"  updated articles:         {updated_total}")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="件数 + 採番プレビューのみ")
    group.add_argument("--apply", action="store_true", help="実際に DB に書き込む")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        return 1

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            try:
                existing = _load_existing_editions(cur)
            except psycopg.errors.UndefinedTable:
                print(
                    "ERROR: editions table does not exist. Apply migrations/004_editions.sql first.",
                    file=sys.stderr,
                )
                return 1

            try:
                _validate_existing_order(existing)
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1

            dates = _load_article_dates(cur)

            if not dates:
                print("✅ Nothing to backfill — all articles already have edition_id.")
                return 0

            counts = _count_articles_per_date(cur, dates)

        plan = _plan(dates, existing)

        if args.dry_run:
            dry_run(plan, counts)
            return 0

        apply(plan, conn)

    print("\n✅ Backfill complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
