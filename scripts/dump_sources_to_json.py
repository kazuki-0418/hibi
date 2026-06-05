"""sources.yaml の有効エントリを web/src/data/sources.json に dump する。

使い方:
    python scripts/dump_sources_to_json.py --dry-run   # 件数のみ
    python scripts/dump_sources_to_json.py --apply     # 実書き出し

Astro の landing page (`web/src/pages/index.astro`) が build 時に読み込み、
sources-strip セクションで「毎朝読むソース一覧」として描画する。

DB を経由しない build-time data injection。`dump_editions_to_json.py` と
同じパターン (idempotent 上書き)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_YAML = REPO_ROOT / "sources.yaml"
OUTPUT_PATH = REPO_ROOT / "web" / "src" / "data" / "sources.json"


def _kind_of(source: dict) -> str:
    """sources.yaml の `type` を UI 表示用ラベルに正規化（digest は RSS-only）。"""
    raw = str(source.get("type", "")).lower()
    if raw == "rss":
        return "RSS"
    return raw.upper() or "Other"


def _to_payload_entry(source: dict) -> dict:
    return {
        "name": str(source["name"]),
        "kind": _kind_of(source),
        "category": str(source.get("category", "")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="件数のみ表示。ファイル書き出しなし")
    group.add_argument("--apply", action="store_true", help="web/src/data/sources.json に書き出す")
    args = parser.parse_args()

    if not SOURCES_YAML.exists():
        print(f"ERROR: {SOURCES_YAML} not found", file=sys.stderr)
        return 1

    with SOURCES_YAML.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    raw_sources = data.get("sources", [])
    enabled = [s for s in raw_sources if s.get("enabled", False)]

    payload = [_to_payload_entry(s) for s in enabled]

    rss_count = sum(1 for p in payload if p["kind"] == "RSS")

    print(f"Sources (enabled): {len(payload)}  (RSS={rss_count})")
    print(f"Output path:       {OUTPUT_PATH}")

    if args.dry_run:
        if payload:
            print("\nSample (first 3):")
            for entry in payload[:3]:
                print(f"  - {entry['name']}  [{entry['kind']}]  category={entry['category']}")
        print("\nRun with --apply to write JSON file.")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {len(payload)} sources to {OUTPUT_PATH}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
