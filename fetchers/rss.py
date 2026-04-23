"""RSS fetcher — feedparser for metadata, trafilatura for article body.

Respects robots.txt per-origin (cached for the duration of the run).
"""

from datetime import datetime, timezone
from time import mktime, struct_time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import trafilatura


USER_AGENT = (
    "PersonalDailyNewsBot/1.0 "
    "(+https://github.com/kazuki-0418/Personal-Daily-News)"
)

_robots_cache: dict[str, RobotFileParser | None] = {}


def _iso_from_struct_time(t: struct_time | None) -> str:
    if t is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(mktime(t), tz=timezone.utc).isoformat()


def fetch_recent_items(source: dict, max_results: int) -> list[dict]:
    """Return the latest entries for an RSS source."""
    feed = feedparser.parse(source["feed_url"])
    if feed.bozo and not feed.entries:
        reason = getattr(feed, "bozo_exception", "unknown")
        print(f"  ⚠️  Failed to parse feed {source['feed_url']}: {reason}")
        return []

    items = []
    for entry in feed.entries[:max_results]:
        url = entry.get("link", "").strip()
        if not url:
            continue
        items.append(
            {
                "source_type": "rss",
                "source_name": source["name"],
                "category": source.get("category"),
                "content_id": url,
                "title": entry.get("title", ""),
                "url": url,
                "published_at": _iso_from_struct_time(
                    entry.get("published_parsed")
                    or entry.get("updated_parsed")
                ),
                "description": entry.get("summary", ""),
            }
        )
    return items


def _robots_allows(url: str) -> bool:
    """Check robots.txt for ``url``. Fails open on fetch errors."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            rp.read()
            _robots_cache[origin] = rp
        except Exception:
            # robots.txt unreachable — fail open so a single broken robots
            # endpoint doesn't silently drop every article.
            _robots_cache[origin] = None

    rp = _robots_cache[origin]
    if rp is None:
        return True
    return rp.can_fetch(USER_AGENT, url)


def get_content_text(item: dict) -> str | None:
    """Fetch and extract the article body text. ``None`` if unavailable."""
    url = item["url"]
    if not _robots_allows(url):
        print(f"    [skip] robots.txt disallows: {url}")
        return None

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        print(f"    [skip] download failed: {url}")
        return None

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
    if not text:
        print(f"    [skip] extraction yielded no text: {url}")
        return None
    return text
