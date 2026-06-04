"""sources.yaml の RSS feed_url を feedparser で検証する。

使い方:
    python scripts/verify_feeds.py sources.yaml

出力:
    ✅ Lenny's Newsletter (20 entries)
    ❌ Bad Feed (NOT FOUND or empty)
"""

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fetchers.rss import parse_feed


def verify_feeds(yaml_path: str) -> int:
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    sources = data.get("sources", [])
    rss_sources = [s for s in sources if s.get("type") == "rss" and s.get("enabled", True)]
    failures = 0

    for source in rss_sources:
        name = source["name"]
        feed_url = source.get("feed_url", "")
        if not feed_url:
            print(f"❌ {name} — missing feed_url")
            failures += 1
            continue

        feed = parse_feed(feed_url)
        entry_count = len(feed.entries) if feed.entries else 0
        if feed.bozo and not feed.entries:
            exc = getattr(feed, "bozo_exception", "parse error")
            print(f"❌ {name} — {feed_url} ({exc})")
            failures += 1
        elif entry_count == 0:
            print(f"❌ {name} — {feed_url} (no entries)")
            failures += 1
        else:
            print(f"✅ {name} ({entry_count} entries) — {feed_url}")

    return failures


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "sources.yaml"
    failed = verify_feeds(path)
    sys.exit(1 if failed else 0)
