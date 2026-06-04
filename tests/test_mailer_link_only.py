"""Regression tests for link-only digest rows in mailer (KAZ-205)."""

import mailer


def test_build_html_accepts_summary_none() -> None:
    articles = [
        {
            "title": "Marc Lou — new upload",
            "url": "https://www.youtube.com/watch?v=example",
            "summary": None,
            "source": "Marc Lou",
            "source_type": "youtube",
        },
        {
            "title": "Regular story",
            "url": "https://example.com/post",
            "summary": "・通常の要約行。",
            "source": "Example Blog",
            "source_type": "rss",
        },
    ]
    html = mailer.build_html(articles, "2026.06.04")
    assert "Marc Lou" in html
    assert "新着動画" in html
    assert "要約なし" in html
    assert "・通常の要約行。" in html


def test_link_only_story_omits_empty_summary_paragraph() -> None:
    html = mailer.build_html(
        [
            {
                "title": "Link only item",
                "url": "https://youtube.example/v",
                "summary": None,
                "source": "Channel",
                "source_type": "youtube",
            }
        ],
        "2026.06.04",
    )
    assert 'class="hb-story-p"' not in html
    assert "hb-story-link-lead" in html
    assert "Link only item" in html


def test_is_link_only_via_flag() -> None:
    html = mailer.build_html(
        [
            {
                "title": "Flagged",
                "url": "https://example.com",
                "summary": "",
                "link_only": True,
                "source": "S",
            }
        ],
        "2026.06.04",
    )
    assert "新着動画" in html
