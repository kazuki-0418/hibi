"""Source-specific fetchers for the Personal AI Newspaper pipeline.

Every fetcher exposes the same two functions:

- ``fetch_recent_items(source, max_results)`` — returns a list of items.
- ``get_content_text(item, ...)`` — returns the body text used for summarization,
  or ``None`` if the content is unavailable.

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
