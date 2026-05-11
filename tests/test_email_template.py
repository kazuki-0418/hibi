"""Template / mailer rendering tests for the design-system migration.

Covered behaviors:
- Story rendering produces numeric prefixes 01..N in order.
- No emoji codepoints appear in the rendered HTML or subject.
- Subject format ``YYYY.MM.DD — 今朝のN本`` (half-width period, em-dash).
- Font stack includes the Google Fonts ``<link>`` plus a system fallback chain.
- Seal SVG is referenced exactly once via a GitHub raw URL.
- ``mailer.send`` signature stays exactly: (subject, articles, date, to,
  from_addr, password) -> None. Old design-system fields (pill / star /
  group) must not appear in the body.
"""
from __future__ import annotations

import inspect
import re
import unicodedata
from typing import Iterable

import mailer
from send_mail import format_subject

SAMPLE_ARTICLES: list[dict] = [
    {
        "title": "Anthropic、Claude Sonnet 4.6 を公開",
        "url": "https://anthropic.example/news/sonnet-4-6",
        "summary": "長文要約とコード生成の精度が前世代比で大幅に向上した。",
        "category": "AI/LLM",
        "source": "Anthropic",
        "source_type": "YouTube",
    },
    {
        "title": "CSS Anchor Positioning がブラウザ三社で揃う",
        "url": "https://web.dev/anchor-positioning",
        "summary": "Firefox 138 で実装が揃った。",
        "category": "Frontend",
        "source": "web.dev",
        "source_type": "RSS",
    },
    {
        "title": "東京の AI スタートアップ二社が同日に調達発表",
        "url": "https://thebridge.example/tokyo-ai",
        "summary": "Sakana AI 系列のスピンアウトが Series A で十二億円を調達。",
        "category": "Startup",
        "source": "Bridge",
        "source_type": "RSS",
    },
    {
        "title": "開発者の燃え尽きについて静かな考察",
        "url": "https://youtube.example/burnout",
        "summary": "十年目のエンジニアが燃え尽き経験を一人語りで振り返る。",
        "category": "Career",
        "source": "Lex Fridman",
        "source_type": "YouTube",
    },
    {
        "title": "Bun 1.4、Node 互換性で実用域へ",
        "url": "https://bun.example/1-4",
        "summary": "Node.js の主要モジュールほぼ全てで互換性テストに通過した。",
        "category": "Tooling",
        "source": "Bun Blog",
        "source_type": "RSS",
    },
]


def _contains_emoji(text: str) -> bool:
    """Return True iff ``text`` contains any Emoji/Symbol/Pictograph codepoints.

    We flag the ranges Hibi's old template leaked into output:
    - Pictographs / dingbats (U+2600..U+27BF)
    - Stars used as importance markers (U+2605, U+2606)
    - Variation selectors that pair with emoji (U+FE0F)
    - Emoji planes (U+1F300..U+1FAFF)
    """
    for ch in text:
        cp = ord(ch)
        if 0x2600 <= cp <= 0x27BF:
            return True
        if cp in (0x2605, 0x2606, 0xFE0F):
            return True
        if 0x1F300 <= cp <= 0x1FAFF:
            return True
        # General Category 'So' (Other Symbol) catches the rest pragmatically.
        if unicodedata.category(ch) == "So":
            return True
    return False


def _all_text(strings: Iterable[str]) -> str:
    return "\n".join(strings)


# ── Story render — numeric prefixes, Masthead / Sources / Colophon ──────


def test_build_html_renders_numeric_prefixes_in_order() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    for i, _ in enumerate(SAMPLE_ARTICLES, start=1):
        # Each story has its 0N prefix in a <td>… numeric cell.
        assert f">{i:02d}</td>" in html, f"expected 0{i} prefix in story {i}"
    # Stories appear in the same order as input.
    positions = [html.index(f">{i:02d}</td>") for i in range(1, 6)]
    assert positions == sorted(positions)


def test_build_html_contains_masthead_sources_and_colophon() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    assert "日々" in html  # Masthead wordmark
    assert "DAILY · TOKYO" in html  # Masthead meta
    assert "今朝の5本。" in html  # Standfirst
    assert "Sources scanned this morning" in html  # Sources label
    assert "日々の小さな知らせ。" in html  # Colophon tagline


def test_build_html_drops_pill_and_star_markup() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    # Old design artifacts must be gone — these would survive into the
    # rendered body if mailer fell back to the pre-design-system template.
    forbidden = ['class="pill', "★", "★★☆", "group-heading", "最重要"]
    for marker in forbidden:
        assert marker not in html, f"unexpected legacy marker {marker!r} in body"


# ── Emoji-free output ──────────────────────────────────────────────────


def test_rendered_html_contains_no_emoji() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    assert not _contains_emoji(html), "rendered email body must not contain emoji"


def test_subject_contains_no_emoji() -> None:
    subject = format_subject("2026.05.10", count=5)
    assert not _contains_emoji(subject), "subject must not contain emoji"


# ── Subject format ─────────────────────────────────────────────────────


def test_subject_format_matches_design_system() -> None:
    subject = format_subject("2026.05.10", count=5)
    assert subject == "2026.05.10 — 今朝の5本"
    # Half-width period + em-dash, not full-width period or hyphen.
    assert "．" not in subject
    assert "—" in subject and "-" not in subject


def test_subject_format_uses_dot_separated_date() -> None:
    # Regex anchors the YYYY.MM.DD shape — guards against ISO-style drift.
    subject = format_subject("2026.05.10", count=5)
    assert re.match(r"^\d{4}\.\d{2}\.\d{2} — 今朝の\d+本$", subject)


# ── Font fallback ──────────────────────────────────────────────────────


def test_html_loads_google_fonts_via_preconnect_and_link() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    assert 'rel="preconnect" href="https://fonts.googleapis.com"' in html
    assert 'rel="preconnect" href="https://fonts.gstatic.com"' in html
    assert "fonts.googleapis.com/css2?family=Noto+Sans+JP" in html


def test_html_includes_system_font_fallback_stack() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    # The fallback chain Gmail/Apple Mail will use when CDN fonts fail.
    # Order matters: Noto Sans JP → system-ui → -apple-system → Yu Gothic →
    # Hiragino Kaku Gothic ProN.
    stack = (
        "'Noto Sans JP',system-ui,-apple-system,"
        "'Yu Gothic','Hiragino Kaku Gothic ProN',sans-serif"
    )
    assert stack in html


# ── Seal SVG via GitHub raw URL ────────────────────────────────────────


def test_seal_svg_referenced_via_github_raw_url_exactly_once() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    matches = re.findall(
        r"https://raw\.githubusercontent\.com/[^\"']+/seal\.svg",
        html,
    )
    assert len(matches) == 1, f"expected exactly one seal.svg raw URL, got {matches!r}"


# ── Hairline rule color (Gmail / Apple Mail) ───────────────────────────


def test_html_uses_design_system_hairline_color() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    # The single hairline color used for rules / borders per design tokens.
    assert "1px solid #E8E6E1" in html
    # No alternative grays leaking from the legacy template.
    assert "#e8ecf0" not in html.lower()


# ── mailer.send interface contract ─────────────────────────────────────


def test_mailer_send_signature_unchanged() -> None:
    sig = inspect.signature(mailer.send)
    params = list(sig.parameters)
    assert params == ["subject", "articles", "date", "to", "from_addr", "password"]
    assert sig.return_annotation is None


def test_build_html_returns_str_with_inline_styles_only() -> None:
    html = mailer.build_html(SAMPLE_ARTICLES, "2026.05.10")
    assert isinstance(html, str) and len(html) > 0
    # The design-system migration inlines tokens via style="…" attributes;
    # no <style> block, no premailer/juice dependency.
    assert "<style" not in html.lower()
    # Token color literals from design-system/colors_and_type.css.
    for token in ("#1A1A1A", "#5C5A57", "#9B9894", "#FAFAF7", "#E8E6E1"):
        assert token in html


# ── HTML escaping of user-controlled fields ────────────────────────────


def test_build_html_escapes_dangerous_chars_in_user_fields() -> None:
    """A feed title containing `&`, `<`, `>`, or a stray `"` must not corrupt
    the rendered Gmail body or break the anchor `href` attribute. The legacy
    `daily_news.build_email_html` escaped these via `html.escape()`; the
    Hibi-template path must preserve that property since it now owns the
    production email render.
    """
    hostile = [{
        "title": 'Anthropic & "Claude" <release>',
        "url": 'https://x.example/p?q="unsafe"&a=<b>',
        "summary": "Body with <script>alert(1)</script> and ampersand & quoted \"text\".",
        "category": 'AI & <ML>',
        "source": 'Source "Bridge" & co.',
        "source_type": 'RSS <feed>',
    }]
    rendered = mailer.build_html(hostile, "2026.05.10")

    # None of the raw dangerous characters survive into the body. We check
    # for the specific dangerous substrings rather than just `<` (which the
    # template legitimately uses) by looking for unescaped attacker payloads.
    assert "<script>" not in rendered, "raw <script> escaped into body"
    assert "<release>" not in rendered, "raw `<release>` survived"
    assert "<ML>" not in rendered, "raw `<ML>` survived"
    assert "<feed>" not in rendered, "raw `<feed>` survived"
    # An href containing an unescaped double quote would break the attribute.
    # The url should have `&quot;` (or `&#x27;`) in place of the literal `"`.
    assert 'href="https://x.example/p?q="' not in rendered, "raw `\"` in href"
    # The escaped form must be present.
    assert "&amp;" in rendered, "ampersand should be escaped to &amp;"
    assert "&lt;" in rendered and "&gt;" in rendered, "angle brackets escaped"
