"""Tests for link-only digest rows when RSS body is unavailable (KAZ-201)."""

from daily_news import (
    LINK_ONLY_SUMMARY,
    _fetch_content,
    _is_link_only_item,
)


def test_rss_with_sufficient_body_is_not_link_only() -> None:
    item = {"source_type": "rss", "content_id": "u1", "url": "https://example.com/a"}
    body = "x" * 600
    assert _is_link_only_item(item, body) is False


def test_rss_without_body_is_link_only() -> None:
    item = {"source_type": "rss", "content_id": "u1", "url": "https://example.com/a"}
    assert _is_link_only_item(item, None) is True


def test_rss_short_body_is_link_only() -> None:
    item = {"source_type": "rss", "content_id": "u1", "url": "https://example.com/a"}
    assert _is_link_only_item(item, "short") is True


def test_link_only_summary_is_none() -> None:
    assert LINK_ONLY_SUMMARY is None


def test_fetch_content_returns_rss_body_via_fetcher(monkeypatch) -> None:
    item = {"source_type": "rss", "content_id": "u1", "url": "https://example.com/a"}

    def fake_get(_item: dict) -> str:
        return "body"

    import fetchers.rss as rss_mod

    monkeypatch.setattr(rss_mod, "get_content_text", fake_get)
    assert _fetch_content(item) == "body"
