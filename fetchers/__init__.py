"""Fetchers for the daily digest pipeline (KAZ-214: RSS-only).

``rss`` exposes ``fetch_recent_items`` for Stage A metadata and
``get_content_text`` for Stage C article bodies.
"""

from fetchers import rss

__all__ = ["rss"]
