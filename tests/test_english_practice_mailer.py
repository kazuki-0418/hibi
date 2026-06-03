"""Mailer rendering for English practice section (KAZ-203)."""

import mailer


def test_build_html_renders_english_practice_section() -> None:
    practice = {
        "prompt_line": (
            "In English (2 sentences): apply this to your job search. "
            "（まず声に出してから書く。）"
        ),
        "paste_request": "Please help me write natural English.\nNot grammar nitpicking.",
        "article_title": "Sample Story",
    }
    html = mailer.build_html(
        [{"title": "T", "url": "https://example.com", "summary": "s", "source": "S"}],
        "2026.06.03",
        english_practice=practice,
    )
    assert "English output" in html
    assert "Paste into Claude" in html
    assert "grammar nitpicking" in html
    assert "まず声に出して" in html


def test_build_html_omits_english_section_when_none() -> None:
    html = mailer.build_html(
        [{"title": "T", "url": "https://example.com", "summary": "s", "source": "S"}],
        "2026.06.03",
    )
    assert "English output" not in html
