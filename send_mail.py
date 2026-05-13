"""
Send daily news email from enriched articles.

Usage:
  python send_mail.py --subject "Daily Tech News - 2026-04-15" \
                      --from-enriched enriched_articles.json
"""
import argparse
import json
import logging
import os
import unicodedata
from datetime import date

from dotenv import load_dotenv
from mailer import send

load_dotenv()

log = logging.getLogger(__name__)

# Design-system limit for email subjects, see design-system/README.md:
# "Email subject: <= 28 zen-kaku chars. Always begins with the date."
_SUBJECT_MAX_FULLWIDTH = 28

# Em-dash used as the legitimate separator in the subject line.
_EM_DASH = "—"
# Katakana prolonged sound mark — must NOT be used as a clause separator.
_KATAKANA_PROLONG = "ー"


def _fullwidth_count(s: str) -> int:
    """Return the visual width of ``s`` measured in zen-kaku (full-width) chars.

    Each character contributes 1.0 if its East Asian Width is Wide / Fullwidth
    / Ambiguous, and 0.5 if it is Narrow / Halfwidth / Neutral. The result is
    rounded up to the next integer so a single trailing half-width char still
    counts as 1 toward the budget.

    This intentionally mirrors how Gmail / Apple Mail render the subject in
    a Japanese-locale inbox list, where ASCII glyphs occupy roughly half the
    advance width of a CJK glyph.
    """
    total: float = 0.0
    for ch in s:
        width = unicodedata.east_asian_width(ch)
        if width in ("W", "F", "A"):
            total += 1.0
        else:
            total += 0.5
    # Round up so 27.5 -> 28 (still within budget) but 28.5 -> 29 (over).
    rounded = int(total)
    if total > rounded:
        rounded += 1
    return rounded


def _has_emoji(s: str) -> bool:
    """Return True iff ``s`` contains any emoji / pictograph codepoint.

    Covers the ranges Hibi's templates leaked into output historically:
    - Pictographs / dingbats (U+2600..U+27BF)
    - Variation selector-16 paired with emoji (U+FE0F)
    - Emoji planes (U+1F300..U+1FAFF) — covers 1F300..1F5FF, 1F600..1F64F
      (smileys, e.g. U+1F600), 1F900..1F9FF, 1FA00..1FAFF.
    - Other-Symbol (Unicode general category ``So``) catches stragglers.
    """
    for ch in s:
        cp = ord(ch)
        if 0x2600 <= cp <= 0x27BF:
            return True
        if cp == 0xFE0F:
            return True
        if 0x1F300 <= cp <= 0x1FAFF:
            return True
        if unicodedata.category(ch) == "So":
            return True
    return False


def _has_dangerous_dash(s: str) -> bool:
    """Return True iff the katakana prolong「ー」is used as a clause separator.

    The subject canonical shape is ``<date> — <body>`` where ``—`` is U+2014.
    A common authoring mistake is typing「ー」(U+30FC) instead, which looks
    similar in a sans-serif font but is semantically wrong (it is the
    katakana long-vowel mark, not a dash).

    Heuristic: flag any「ー」that is surrounded by spaces (likely used as a
    separator), or any「ー」at all when the subject does NOT also contain a
    real em-dash — that combination means the author tried to write the
    separator and reached for the wrong key.
    """
    if _KATAKANA_PROLONG not in s:
        return False
    if _EM_DASH not in s:
        # No real em-dash present, so the only candidate for the separator
        # role is the prolong mark — flag it.
        return True
    # Em-dash is present, but a prolong mark surrounded by ASCII spaces is
    # also suspicious (likely a second, accidental separator).
    if f" {_KATAKANA_PROLONG} " in s:
        return True
    return False


def format_subject(date_str: str, count: int) -> str:
    """Build the daily subject line.

    Format: ``YYYY.MM.DD — 今朝のN本`` (half-width period + em-dash, no emoji).

    Soft validation: the function ALWAYS returns the formatted subject. If
    the result violates design-system constraints (over 28 zen-kaku chars,
    contains emoji, or contains a misused「ー」), the violation is logged at
    WARNING level so the daily pipeline keeps running and the operator can
    see the regression in logs.
    """
    subject = f"{date_str} {_EM_DASH} 今朝の{count}本"

    width = _fullwidth_count(subject)
    if width > _SUBJECT_MAX_FULLWIDTH:
        log.warning(
            "email subject exceeds design-system width budget: "
            "%d full-width chars > %d (subject=%r)",
            width,
            _SUBJECT_MAX_FULLWIDTH,
            subject,
        )

    if _has_emoji(subject):
        log.warning(
            "email subject contains emoji / pictograph codepoint (subject=%r)",
            subject,
        )

    if _has_dangerous_dash(subject):
        log.warning(
            "email subject uses katakana prolong mark instead of em-dash "
            "(subject=%r)",
            subject,
        )

    return subject


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", default=None, help="Email subject (default: auto-generated)")
    parser.add_argument("--from-enriched", dest="from_enriched", default="enriched_articles.json")
    parser.add_argument("--date", default=None, help="Date string shown in email header (default: today)")
    args = parser.parse_args()

    date_str = args.date or date.today().strftime("%Y.%m.%d")

    with open(args.from_enriched, encoding="utf-8") as f:
        articles = json.load(f)

    subject = args.subject or format_subject(date_str, count=len(articles))

    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    send(
        subject=subject,
        articles=articles,
        date=date_str,
        to=gmail_address,
        from_addr=gmail_address,
        password=gmail_password,
    )
    print(f"Email sent: {subject}")


if __name__ == "__main__":
    main()
