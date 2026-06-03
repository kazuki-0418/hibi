"""Tests for YouTube metadata-only digest rows (KAZ-200)."""

from daily_news import LINK_ONLY_SUMMARY, _fetch_content, _is_link_only_item


def test_youtube_is_link_only() -> None:
    item = {"source_type": "youtube", "content_id": "abc", "url": "https://youtu.be/abc"}
    assert _is_link_only_item(item) is True


def test_rss_is_not_link_only() -> None:
    item = {"source_type": "rss", "url": "https://example.com/x"}
    assert _is_link_only_item(item) is False


def test_fetch_content_returns_none_for_youtube() -> None:
    item = {"source_type": "youtube", "content_id": "abc", "url": "https://youtu.be/abc"}
    assert _fetch_content(item) is None


def test_link_only_summary_is_none() -> None:
    assert LINK_ONLY_SUMMARY is None
