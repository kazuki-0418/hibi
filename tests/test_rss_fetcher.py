"""Unit tests for fetchers.rss robots.txt and body fetch (KAZ-201)."""

from unittest.mock import MagicMock, patch

import fetchers.rss as rss


def setup_function() -> None:
    rss.clear_robots_cache()


def test_robots_disallows_skips_body_fetch() -> None:
    item = {"url": "https://example.com/article"}
    with patch.object(rss, "_robots_allows", return_value=False):
        with patch.object(rss.trafilatura, "fetch_url") as mock_fetch:
            assert rss.get_content_text(item) is None
            mock_fetch.assert_not_called()


def test_robots_fetch_failure_fails_closed() -> None:
    with patch.object(rss, "urlopen", side_effect=OSError("network")):
        assert rss._robots_allows("https://blocked.example/post") is False


def test_robots_disallow_path_blocks_fetch() -> None:
    robots_body = "User-agent: *\nDisallow: /private/\n"
    fake_resp = MagicMock()
    fake_resp.read.return_value = robots_body.encode()
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch.object(rss, "urlopen", return_value=fake_resp):
        assert rss._robots_allows("https://site.test/private/secret") is False
        assert rss._robots_allows("https://site.test/public/ok") is True


def test_get_content_text_returns_extracted_body() -> None:
    item = {"url": "https://example.com/story"}
    with patch.object(rss, "_robots_allows", return_value=True):
        with patch.object(rss.trafilatura, "fetch_url", return_value="<html/>"):
            with patch.object(rss.trafilatura, "extract", return_value="x" * 600):
                text = rss.get_content_text(item)
    assert text is not None
    assert len(text) == 600


def test_trafilatura_config_sets_user_agent() -> None:
    rss._cached_trafilatura_config = None
    config = rss._trafilatura_config()
    assert config.get("DEFAULT", "USER_AGENT") == rss.USER_AGENT


def test_parse_feed_uses_pipeline_user_agent() -> None:
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.entries = []
    with patch.object(rss.feedparser, "parse", return_value=mock_feed) as mock_parse:
        rss.parse_feed("https://example.com/feed")
    mock_parse.assert_called_once_with(
        "https://example.com/feed",
        agent=rss.USER_AGENT,
    )


def test_fetch_recent_items_uses_parse_feed() -> None:
    source = {"name": "Test", "feed_url": "https://example.com/feed"}
    with patch.object(rss, "parse_feed") as mock_parse:
        mock_parse.return_value = MagicMock(bozo=False, entries=[])
        rss.fetch_recent_items(source, 3)
    mock_parse.assert_called_once_with("https://example.com/feed")
