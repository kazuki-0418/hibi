"""Source-specific fetchers for the Personal AI Newspaper pipeline.

Every fetcher exposes ``fetch_recent_items`` for Stage A metadata.

RSS also exposes ``get_content_text`` for Stage C article bodies. YouTube is
metadata-only (link rows in the digest; no transcript).

Unified item shape:

    {
        "source_type":  "youtube" | "rss",
        "source_name":  str,
        "category":     str | None,
        "content_id":   str,   # video_id for YT, canonical URL for RSS
        "title":        str,
        "url":          str,
        "published_at": str,   # ISO 8601 (UTC)
        "description":  str,
    }
"""

from fetchers import rss, youtube

__all__ = ["rss", "youtube"]
