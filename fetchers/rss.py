"""RSS fetcher — feedparser for metadata, trafilatura for article body.

Respects robots.txt per-origin (cached for the duration of the run).
When robots.txt cannot be fetched, the origin is treated as disallowed (fail closed).
"""

from configparser import ConfigParser
from datetime import datetime, timezone
from time import mktime, struct_time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

import feedparser
import trafilatura
from trafilatura.settings import use_config


USER_AGENT = (
    "PersonalDailyNewsBot/1.0 "
    "(+https://github.com/kazuki-0418/Personal-Daily-News)"
)

ROBOTS_FETCH_TIMEOUT_SEC = 10

_robots_cache: dict[str, RobotFileParser | None] = {}
_cached_trafilatura_config: ConfigParser | None = None


def clear_robots_cache() -> None:
    """Reset per-run robots cache (for tests)."""
    _robots_cache.clear()


def _trafilatura_config() -> ConfigParser:
    global _cached_trafilatura_config
    if _cached_trafilatura_config is None:
        config = use_config()
        config.set("DEFAULT", "USER_AGENT", USER_AGENT)
        _cached_trafilatura_config = config
    return _cached_trafilatura_config


def _iso_from_struct_time(t: struct_time | None) -> str:
    if t is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(mktime(t), tz=timezone.utc).isoformat()


def parse_feed(feed_url: str):
    """Parse an RSS/Atom feed with the pipeline User-Agent (KAZ-207).

    Substack and Cloudflare often return 403 + HTML to the default
    ``Python-urllib/*`` agent feedparser would use, which surfaces as
    ``not well-formed (invalid token)`` XML parse errors.
    """
    return feedparser.parse(feed_url, agent=USER_AGENT)


def fetch_recent_items(source: dict, max_results: int) -> list[dict]:
    """Return the latest entries for an RSS source."""
    feed = parse_feed(source["feed_url"])
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


def _load_robots_parser(origin: str) -> RobotFileParser | None:
    """Fetch and parse robots.txt for ``origin``. ``None`` on any failure."""
    robots_url = f"{origin}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    req = Request(robots_url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=ROBOTS_FETCH_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        rp.parse(body.splitlines())
        return rp
    except Exception:
        return None


def _robots_allows(url: str) -> bool:
    """Return whether ``USER_AGENT`` may fetch ``url`` per robots.txt.

    Disallows when robots.txt fetch/parse fails (fail closed).
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin not in _robots_cache:
        _robots_cache[origin] = _load_robots_parser(origin)

    rp = _robots_cache[origin]
    if rp is None:
        return False
    return rp.can_fetch(USER_AGENT, url)


def get_content_text(item: dict) -> str | None:
    """Fetch and extract the article body text. ``None`` if unavailable."""
    url = item["url"]
    if not _robots_allows(url):
        print(f"    [skip] robots.txt disallows: {url}")
        return None

    downloaded = trafilatura.fetch_url(url, config=_trafilatura_config())
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
