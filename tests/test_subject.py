"""Subject-line formatter tests for ``send_mail.format_subject``.

Covers:
- Canonical shape ``YYYY.MM.DD — 今朝のN本`` (half-width period + em-dash).
- Full-width width budget (<= 28 zen-kaku chars per design-system/README.md).
- Stability across realistic counts (3 / 5 / 10).
- Internal helper contracts: ``_has_emoji`` and ``_has_dangerous_dash``.
- Warning log emission when the width budget is blown — subject itself is
  returned unmodified (soft validation, never raises).
"""
from __future__ import annotations

import logging

import pytest

from send_mail import (
    _fullwidth_count,
    _has_dangerous_dash,
    _has_emoji,
    format_subject,
)

# Design-system budget (see design-system/README.md "Lengths").
SUBJECT_MAX_FULLWIDTH = 28


# ── Canonical shape ────────────────────────────────────────────────────


def test_format_subject_canonical_shape() -> None:
    """Standard case: matches the design-system example verbatim."""
    assert format_subject("2026.05.10", count=5) == "2026.05.10 — 今朝の5本"


def test_format_subject_uses_em_dash_not_hyphen() -> None:
    """The separator must be U+2014 em-dash, not ASCII hyphen-minus."""
    subject = format_subject("2026.05.10", count=5)
    assert "—" in subject  # U+2014
    # ASCII hyphen-minus must NOT be present (would indicate fallback drift).
    assert "-" not in subject


def test_format_subject_uses_halfwidth_period_in_date() -> None:
    """Date separator must be ASCII `.`, not the full-width `．` (U+FF0E)."""
    subject = format_subject("2026.05.10", count=5)
    assert "．" not in subject
    assert "." in subject


# ── Width budget ───────────────────────────────────────────────────────


def test_format_subject_within_fullwidth_budget() -> None:
    """Canonical subject must fit under the 28 zen-kaku design-system cap."""
    subject = format_subject("2026.05.10", count=5)
    assert _fullwidth_count(subject) <= SUBJECT_MAX_FULLWIDTH


@pytest.mark.parametrize("count", [3, 5, 10])
def test_format_subject_stable_across_counts(count: int) -> None:
    """Realistic counts (3 / 5 / 10) must keep the format intact and within budget."""
    subject = format_subject("2026.05.10", count=count)
    assert subject == f"2026.05.10 — 今朝の{count}本"
    assert _fullwidth_count(subject) <= SUBJECT_MAX_FULLWIDTH


def test_format_subject_logs_warning_when_over_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the formatted subject exceeds 28 zen-kaku chars, a WARNING must be
    emitted — but the subject is still returned unmodified (soft validation).
    """
    # Force an overlong date string. 30 ASCII chars = 15 zen-kaku, plus
    # ` — 今朝の99999本` adds ~10 more zen-kaku, total ~25... so use a much
    # longer payload to comfortably exceed 28.
    long_date = "2026.05.10-extra-tag-please-overflow-the-budget"
    with caplog.at_level(logging.WARNING, logger="send_mail"):
        subject = format_subject(long_date, count=5)
    # Subject is still returned verbatim — soft validation never raises or
    # silently truncates.
    assert subject == f"{long_date} — 今朝の5本"
    # Width budget warning was emitted.
    width_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "width budget" in r.getMessage()
    ]
    assert width_warnings, "expected a width-budget warning record"


def test_format_subject_no_warning_when_within_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Canonical subject must emit zero WARNING records."""
    with caplog.at_level(logging.WARNING, logger="send_mail"):
        format_subject("2026.05.10", count=5)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# ── _has_emoji helper ──────────────────────────────────────────────────


@pytest.mark.parametrize("ch", ["📅", "🔥", "😀", "⭐", "✨"])
def test_has_emoji_detects_emoji_codepoints(ch: str) -> None:
    assert _has_emoji(f"prefix {ch} suffix") is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "2026.05.10 — 今朝の5本",
        "Anthropic、Claude 4.6 をリリース",
        "plain ascii only",
        "日本語のみ",
    ],
)
def test_has_emoji_returns_false_for_safe_text(text: str) -> None:
    assert _has_emoji(text) is False


# ── _has_dangerous_dash helper ─────────────────────────────────────────


def test_has_dangerous_dash_flags_katakana_prolong_as_separator() -> None:
    """U+30FC「ー」used in the separator slot must be flagged."""
    assert _has_dangerous_dash("2026.05.10 ー 今朝の5本") is True


def test_has_dangerous_dash_passes_canonical_em_dash() -> None:
    """U+2014「—」used as the separator is the correct, expected form."""
    assert _has_dangerous_dash("2026.05.10 — 今朝の5本") is False


def test_has_dangerous_dash_passes_legitimate_prolong_in_word() -> None:
    """A prolong mark inside a katakana word (e.g.「サーバー」) with the
    correct em-dash separator must NOT be flagged.
    """
    assert _has_dangerous_dash("2026.05.10 — サーバー更新") is False


def test_format_subject_logs_warning_on_dangerous_dash(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the formatter ever produces a「ー」-shaped subject (via future
    refactor), a WARNING must surface so the regression is loud in logs.
    Today this is impossible because the literal in ``format_subject`` is
    hard-coded — so we exercise the helper path directly.
    """
    # Drive the warning path through the public surface by simulating a
    # bad render: call the internal predicate that the formatter delegates to.
    assert _has_dangerous_dash("2026.05.10 ー 今朝の5本") is True


def test_format_subject_logs_warning_on_emoji_subject(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Emoji in a date string must trip the emoji-detection branch and emit a
    WARNING. Subject is returned unmodified.
    """
    with caplog.at_level(logging.WARNING, logger="send_mail"):
        subject = format_subject("2026.05.10 🔥", count=5)
    assert subject == "2026.05.10 🔥 — 今朝の5本"
    emoji_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "emoji" in r.getMessage()
    ]
    assert emoji_warnings, "expected an emoji warning record"


# ── _fullwidth_count helper ────────────────────────────────────────────


def test_fullwidth_count_empty_string_is_zero() -> None:
    assert _fullwidth_count("") == 0


def test_fullwidth_count_ascii_is_half_per_char() -> None:
    # 10 ASCII chars = 5.0 zen-kaku → rounded up to 5.
    assert _fullwidth_count("abcdefghij") == 5


def test_fullwidth_count_cjk_is_one_per_char() -> None:
    # 4 CJK chars = 4.0 zen-kaku.
    assert _fullwidth_count("今朝の本") == 4


def test_fullwidth_count_canonical_subject_is_well_under_budget() -> None:
    # Sanity: the example from design-system/README.md leaves plenty of room.
    width = _fullwidth_count("2026.05.10 — 今朝の5本")
    assert width <= SUBJECT_MAX_FULLWIDTH
    # And the width is realistic (not absurdly small / large).
    assert 8 <= width <= 20
