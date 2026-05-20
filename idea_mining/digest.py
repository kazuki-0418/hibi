"""Weekly idea-digest mailer.

Issue #140 (Epic #134): 毎週月曜 00:00 UTC (= 09:00 JST) に直近 ISO 週の
`patterns` (frequency 降順 Top 3) と各 pattern に紐づく Critic verdict 付き
`candidates` (GO 最大 2 件 / KILL 最大 1 件) を Gmail で配信する。

newspaper pipeline (`daily_news.py` / `articles` / ranking / mailer) からは
独立した経路。`patterns` / `candidates` テーブルは **read-only** で扱う。
配信先は ``RECIPIENT_EMAIL`` 1 アドレス固定 (multi-tenant 化しない)。

Failure modes:
    * 対象週の patterns ゼロ / 表示候補ゼロ → 送信スキップ (exit 0)。
    * DB / Gmail 例外は raise する。workflow が failure として扱う。

DRY_RUN:
    env ``DIGEST_DRY_RUN=1`` または workflow_dispatch 入力で有効化。
    stdout に subject + plain text 本文を出して終わる (Gmail 呼び出しなし)。

CLI:
    python -m idea_mining.digest

Required env:
    DATABASE_URL          — Neon (psycopg 3.x)
    RECIPIENT_EMAIL       — 配信先 (kazuki 固定)
    GMAIL_CLIENT_ID       — OAuth2
    GMAIL_CLIENT_SECRET   — OAuth2
    GMAIL_REFRESH_TOKEN   — OAuth2 (Production consent screen 前提)

Optional env:
    DIGEST_DRY_RUN=1      — stdout 出力のみ、送信しない
    DIGEST_WEEK_ISO       — 強制的に対象週 (YYYY-Www) を上書き (テスト用)
    DIGEST_VAULT_NAME     — obsidian:// link の vault 名上書き (default:
                            ``Obsidan-workspace``、Issue #140 spec のまま)
"""
from __future__ import annotations

import html
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final
from urllib.parse import quote

import psycopg

import email_sender

log = logging.getLogger(__name__)

# 既存 vault clone は `Obsidan-workspace` (typo はリポ名に由来。本 Issue
# spec の obsidian://open?vault=Obsidan-workspace&file=... と一致)。
DEFAULT_VAULT_NAME: Final[str] = "Obsidan-workspace"

# Vault 内で「週次 pattern note」を置く慣習パス。
# `${OBSIDIAN_VAULT_ROOT}/10_projects/hibi/idea-mining/profile/` が
# 既存基盤なので、その隣に patterns/<week>/<slug>.md を置く想定。
VAULT_PATTERN_DIR: Final[str] = "10_projects/hibi/idea-mining/patterns"

# 表示件数 (acceptance criteria より固定)。
TOP_PATTERNS: Final[int] = 3
MAX_GO_PER_PATTERN: Final[int] = 2
MAX_KILL_PER_PATTERN: Final[int] = 1

DRY_RUN_ENV: Final[str] = "DIGEST_DRY_RUN"
WEEK_ISO_ENV: Final[str] = "DIGEST_WEEK_ISO"
VAULT_NAME_ENV: Final[str] = "DIGEST_VAULT_NAME"

SELECT_TOP_PATTERNS_SQL: Final[str] = """
    SELECT id, pain, categories, frequency, source_diversity, confidence
    FROM patterns
    WHERE week_iso = %s
    ORDER BY frequency DESC, pain ASC
    LIMIT %s
"""

# verdict が NULL の候補は除外 (acceptance: 「verdict 付き candidates」のみ
# 表示)。GO は最新を優先、KILL も最新を優先。同一 pattern 内で何件来ても、
# 呼び出し側で GO 2 件 / KILL 1 件にトリムする。
SELECT_VERDICT_CANDIDATES_SQL: Final[str] = """
    SELECT id, name, one_liner, target_user, monetization, why_different,
           killer_use_case, critic_verdict, critic_meta
    FROM candidates
    WHERE pattern_id = %s
      AND critic_verdict IS NOT NULL
    ORDER BY generated_at DESC, id DESC
"""


# ----------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Pattern:
    id: str  # uuid stringified
    pain: str
    categories: list[str]
    frequency: int
    source_diversity: int
    confidence: float


@dataclass(frozen=True)
class Candidate:
    id: int
    name: str
    one_liner: str | None
    target_user: str | None
    monetization: str | None
    why_different: str | None
    killer_use_case: str | None
    critic_verdict: str  # 'GO' / 'PENDING' / 'KILL'
    kill_reasons: list[str]


@dataclass(frozen=True)
class DigestSection:
    pattern: Pattern
    obsidian_url: str
    go_candidates: list[Candidate] = field(default_factory=list)
    kill_candidates: list[Candidate] = field(default_factory=list)

    @property
    def displayed_count(self) -> int:
        return len(self.go_candidates) + len(self.kill_candidates)


@dataclass(frozen=True)
class Digest:
    week_iso: str
    sections: list[DigestSection]

    @property
    def total_candidates(self) -> int:
        return sum(s.displayed_count for s in self.sections)

    @property
    def should_skip(self) -> bool:
        # patterns が無い、または verdict 付き候補が 1 件も displayable で
        # ないなら配信スキップ (acceptance criteria より)。
        return not self.sections or self.total_candidates == 0


# ----------------------------------------------------------------------
# Week / vault helpers
# ----------------------------------------------------------------------


def current_week_iso(now: datetime | None = None) -> str:
    """Return ISO week as ``YYYY-Www`` (zero-padded week)."""
    if now is None:
        now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


_SLUG_NON_ALNUM = re.compile(r"[^0-9A-Za-z぀-ヿ㐀-鿿]+")


def _slugify_pain(pain: str) -> str:
    """Return a filesystem-safe slug for a `pain` label.

    Strips leading/trailing separators and collapses runs to a single ``-``.
    Keeps ASCII alphanumerics and CJK so the Obsidian link is still readable
    in Japanese. Falls back to ``pattern`` if the result is empty.
    """
    cleaned = _SLUG_NON_ALNUM.sub("-", pain).strip("-")
    return cleaned or "pattern"


def build_obsidian_link(
    week_iso: str, pain: str, *, vault_name: str = DEFAULT_VAULT_NAME
) -> str:
    """Build an ``obsidian://open?vault=...&file=...`` URL for a pattern note.

    File path convention (Issue #140; aligned with existing
    ``10_projects/hibi/idea-mining/profile/`` layout):

        10_projects/hibi/idea-mining/patterns/<week_iso>/<slug>.md
    """
    slug = _slugify_pain(pain)
    file_path = f"{VAULT_PATTERN_DIR}/{week_iso}/{slug}.md"
    return (
        f"obsidian://open?vault={quote(vault_name, safe='')}"
        f"&file={quote(file_path, safe='')}"
    )


# ----------------------------------------------------------------------
# DB I/O
# ----------------------------------------------------------------------


def fetch_top_patterns(
    conn: psycopg.Connection, week_iso: str, *, limit: int = TOP_PATTERNS
) -> list[Pattern]:
    """Return top patterns for ``week_iso`` ordered by frequency DESC."""
    with conn.cursor() as cur:
        cur.execute(SELECT_TOP_PATTERNS_SQL, (week_iso, limit))
        rows = cur.fetchall()
    out: list[Pattern] = []
    for row in rows:
        pattern_id, pain, categories, frequency, source_diversity, confidence = row
        out.append(
            Pattern(
                id=str(pattern_id),
                pain=str(pain),
                categories=list(categories) if categories else [],
                frequency=int(frequency),
                source_diversity=int(source_diversity),
                confidence=float(confidence),
            )
        )
    return out


def _extract_kill_reasons(critic_meta: object) -> list[str]:
    """Pull ``kill_reasons`` out of the JSONB blob, tolerating shape drift."""
    if not isinstance(critic_meta, dict):
        return []
    raw = critic_meta.get("kill_reasons")
    if not isinstance(raw, list):
        return []
    return [str(r) for r in raw if isinstance(r, str) and r.strip()]


def fetch_verdict_candidates(
    conn: psycopg.Connection, pattern_id: str
) -> list[Candidate]:
    """Return candidates for ``pattern_id`` where critic_verdict IS NOT NULL."""
    with conn.cursor() as cur:
        cur.execute(SELECT_VERDICT_CANDIDATES_SQL, (pattern_id,))
        rows = cur.fetchall()
    out: list[Candidate] = []
    for row in rows:
        (
            cid,
            name,
            one_liner,
            target_user,
            monetization,
            why_different,
            killer_use_case,
            verdict,
            critic_meta,
        ) = row
        out.append(
            Candidate(
                id=int(cid),
                name=str(name),
                one_liner=None if one_liner is None else str(one_liner),
                target_user=None if target_user is None else str(target_user),
                monetization=None if monetization is None else str(monetization),
                why_different=None if why_different is None else str(why_different),
                killer_use_case=(
                    None if killer_use_case is None else str(killer_use_case)
                ),
                critic_verdict=str(verdict),
                kill_reasons=_extract_kill_reasons(critic_meta),
            )
        )
    return out


# ----------------------------------------------------------------------
# Digest assembly
# ----------------------------------------------------------------------


def _trim_for_display(
    candidates: list[Candidate],
) -> tuple[list[Candidate], list[Candidate]]:
    """Pick up to 2 GO + 1 KILL, preserving DB ordering (newest-first)."""
    go = [c for c in candidates if c.critic_verdict == "GO"][:MAX_GO_PER_PATTERN]
    kill = [c for c in candidates if c.critic_verdict == "KILL"][:MAX_KILL_PER_PATTERN]
    return go, kill


def build_digest(
    conn: psycopg.Connection,
    week_iso: str,
    *,
    vault_name: str = DEFAULT_VAULT_NAME,
) -> Digest:
    """Assemble the digest payload for ``week_iso``."""
    patterns = fetch_top_patterns(conn, week_iso)
    sections: list[DigestSection] = []
    for p in patterns:
        candidates = fetch_verdict_candidates(conn, p.id)
        go, kill = _trim_for_display(candidates)
        sections.append(
            DigestSection(
                pattern=p,
                obsidian_url=build_obsidian_link(
                    week_iso, p.pain, vault_name=vault_name
                ),
                go_candidates=go,
                kill_candidates=kill,
            )
        )
    return Digest(week_iso=week_iso, sections=sections)


# ----------------------------------------------------------------------
# Rendering — subject + plain text + HTML
# ----------------------------------------------------------------------


def format_subject(digest: Digest) -> str:
    """``[Hibi] 今週のアイデア候補 N 件 (YYYY-Www)`` (N = displayed)."""
    return (
        f"[Hibi] 今週のアイデア候補 {digest.total_candidates} 件 "
        f"({digest.week_iso})"
    )


def _format_go_text(c: Candidate) -> str:
    lines = [f"  ▸ GO: {c.name}"]
    if c.one_liner:
        lines.append(f"    {c.one_liner}")
    if c.target_user:
        lines.append(f"    対象: {c.target_user}")
    return "\n".join(lines)


def _format_kill_text(c: Candidate) -> str:
    lines = [f"  ▸ KILL: {c.name}"]
    if c.one_liner:
        lines.append(f"    {c.one_liner}")
    if c.kill_reasons:
        for reason in c.kill_reasons:
            lines.append(f"    理由: {reason}")
    else:
        lines.append("    理由: (critic_meta に kill_reasons 未収載)")
    return "\n".join(lines)


def render_plain_text(digest: Digest) -> str:
    """Render the digest as plain text (multipart/alternative の text part)."""
    parts: list[str] = []
    parts.append(format_subject(digest))
    parts.append("")
    for i, section in enumerate(digest.sections, 1):
        p = section.pattern
        parts.append(
            f"## {i:02d}. {p.pain}  "
            f"(frequency: {p.frequency}, sources: {p.source_diversity})"
        )
        parts.append(f"Vault: {section.obsidian_url}")
        parts.append("")
        if not section.go_candidates and not section.kill_candidates:
            parts.append("  (verdict 付き候補なし)")
        for c in section.go_candidates:
            parts.append(_format_go_text(c))
        for c in section.kill_candidates:
            parts.append(_format_kill_text(c))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


# Hibi design-system tokens (`design-system/colors_and_type.css` の値を inline。
# Email クライアントは外部 CSS を引かないため `colors_and_type.css` を直接
# 参照できず、token 値をここに固定する必要がある。値が変わったら
# design-system 側の単一の真実に追従する)。
_FONT_JP = (
    "'Noto Sans JP',system-ui,-apple-system,"
    "'Yu Gothic','Hiragino Kaku Gothic ProN',sans-serif"
)
_FONT_EN = "'Inter',system-ui,-apple-system,sans-serif"
_TEXT_PRIMARY = "#1A1A1A"
_TEXT_MUTED = "#5C5A57"
_TEXT_DIM = "#9B9894"
_HAIRLINE = "#E8E6E1"
_BG = "#FAFAF7"

_BODY_STYLE = (
    f"background:{_BG};margin:0;padding:0;"
    f"font-family:{_FONT_JP};color:{_TEXT_PRIMARY};"
)
_CONTAINER_STYLE = (
    "max-width:680px;margin:0 auto;padding:32px 24px;background:#fff;"
)
_H1_STYLE = (
    f"font-family:{_FONT_JP};font-size:22px;font-weight:700;line-height:1.4;"
    f"color:{_TEXT_PRIMARY};margin:0 0 4px;letter-spacing:-0.01em;"
)
_LEDE_STYLE = (
    f"font-family:{_FONT_EN};font-size:11px;letter-spacing:0.25em;"
    f"text-transform:uppercase;color:{_TEXT_DIM};margin:0 0 32px;"
)
_SECTION_STYLE = (
    f"padding:24px 0;border-top:1px solid {_HAIRLINE};"
)
_PATTERN_NUM_STYLE = (
    f"font-family:{_FONT_EN};font-variant-numeric:tabular-nums;"
    f"font-size:13px;letter-spacing:0.2em;color:{_TEXT_DIM};margin:0 0 6px;"
)
_PATTERN_H2_STYLE = (
    f"font-family:{_FONT_JP};font-size:18px;font-weight:700;line-height:1.4;"
    f"color:{_TEXT_PRIMARY};margin:0 0 8px;"
)
_PATTERN_META_STYLE = (
    f"font-family:{_FONT_EN};font-size:11px;letter-spacing:0.15em;"
    f"text-transform:uppercase;color:{_TEXT_DIM};margin:0 0 12px;"
)
_VAULT_LINK_STYLE = (
    f"font-family:{_FONT_EN};font-size:12px;color:{_TEXT_PRIMARY};"
    f"border-bottom:1px solid {_TEXT_PRIMARY};text-decoration:none;"
)
_VERDICT_LABEL_GO_STYLE = (
    f"display:inline-block;font-family:{_FONT_EN};font-size:11px;"
    f"letter-spacing:0.2em;color:{_TEXT_PRIMARY};border:1px solid "
    f"{_TEXT_PRIMARY};padding:1px 6px;margin-right:8px;"
)
_VERDICT_LABEL_KILL_STYLE = (
    f"display:inline-block;font-family:{_FONT_EN};font-size:11px;"
    f"letter-spacing:0.2em;color:{_TEXT_MUTED};border:1px solid "
    f"{_TEXT_MUTED};padding:1px 6px;margin-right:8px;"
)
_CAND_NAME_STYLE = (
    f"font-family:{_FONT_JP};font-size:15px;font-weight:600;"
    f"color:{_TEXT_PRIMARY};"
)
_CAND_LINE_STYLE = (
    f"font-family:{_FONT_JP};font-size:14px;line-height:1.7;"
    f"color:{_TEXT_MUTED};margin:4px 0 0;"
)
_REASON_STYLE = (
    f"font-family:{_FONT_JP};font-size:13px;line-height:1.7;"
    f"color:{_TEXT_MUTED};margin:4px 0 0;"
)
_EMPTY_NOTE_STYLE = (
    f"font-family:{_FONT_JP};font-size:13px;color:{_TEXT_DIM};margin:8px 0 0;"
)
_FOOTER_STYLE = (
    f"font-family:{_FONT_EN};font-size:10px;letter-spacing:0.2em;"
    f"text-transform:uppercase;color:{_TEXT_DIM};margin:40px 0 0;"
    f"padding-top:24px;border-top:1px solid {_HAIRLINE};"
)


def _render_candidate_html(c: Candidate, label: str, label_style: str) -> str:
    name = html.escape(c.name)
    pieces: list[str] = [
        f'<div style="margin:14px 0 0;">'
        f'<span style="{label_style}">{label}</span>'
        f'<span style="{_CAND_NAME_STYLE}">{name}</span>'
        f'</div>'
    ]
    if c.one_liner:
        pieces.append(
            f'<p style="{_CAND_LINE_STYLE}">{html.escape(c.one_liner)}</p>'
        )
    if c.target_user and label == "GO":
        pieces.append(
            f'<p style="{_CAND_LINE_STYLE}">対象: {html.escape(c.target_user)}</p>'
        )
    if label == "KILL":
        reasons = c.kill_reasons or ["(critic_meta に kill_reasons 未収載)"]
        for reason in reasons:
            pieces.append(
                f'<p style="{_REASON_STYLE}">理由: {html.escape(reason)}</p>'
            )
    return "".join(pieces)


def _render_section_html(index: int, section: DigestSection) -> str:
    p = section.pattern
    parts: list[str] = [f'<section style="{_SECTION_STYLE}">']
    parts.append(f'<p style="{_PATTERN_NUM_STYLE}">PATTERN {index:02d}</p>')
    parts.append(f'<h2 style="{_PATTERN_H2_STYLE}">{html.escape(p.pain)}</h2>')
    parts.append(
        f'<p style="{_PATTERN_META_STYLE}">'
        f'frequency {p.frequency} · sources {p.source_diversity}'
        f'</p>'
    )
    parts.append(
        f'<p style="margin:0 0 8px;">'
        f'<a href="{html.escape(section.obsidian_url, quote=True)}" '
        f'style="{_VAULT_LINK_STYLE}">Vault note を開く</a>'
        f'</p>'
    )
    if not section.go_candidates and not section.kill_candidates:
        parts.append(
            f'<p style="{_EMPTY_NOTE_STYLE}">verdict 付き候補なし。</p>'
        )
    for c in section.go_candidates:
        parts.append(_render_candidate_html(c, "GO", _VERDICT_LABEL_GO_STYLE))
    for c in section.kill_candidates:
        parts.append(
            _render_candidate_html(c, "KILL", _VERDICT_LABEL_KILL_STYLE)
        )
    parts.append("</section>")
    return "".join(parts)


def render_html(digest: Digest) -> str:
    """Render the digest as Hibi-design HTML body."""
    sections_html = "".join(
        _render_section_html(i, s) for i, s in enumerate(digest.sections, 1)
    )
    return (
        '<!doctype html>'
        '<html lang="ja"><head>'
        '<meta charset="utf-8">'
        f'<title>{html.escape(format_subject(digest))}</title>'
        '</head>'
        f'<body style="{_BODY_STYLE}">'
        f'<div style="{_CONTAINER_STYLE}">'
        f'<h1 style="{_H1_STYLE}">今週のアイデア候補</h1>'
        f'<p style="{_LEDE_STYLE}">'
        f"Hibi idea mining · {html.escape(digest.week_iso)} · "
        f"{digest.total_candidates} candidates"
        f'</p>'
        f'{sections_html}'
        f'<p style="{_FOOTER_STYLE}">'
        f"Hibi · private digest"
        f'</p>'
        '</div></body></html>'
    )


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------


def _dry_run_enabled() -> bool:
    return os.environ.get(DRY_RUN_ENV) == "1"


def run(
    conn: psycopg.Connection,
    *,
    week_iso: str,
    recipient: str,
    dry_run: bool,
    vault_name: str = DEFAULT_VAULT_NAME,
) -> str:
    """End-to-end one-shot run. Returns the outcome label for logging.

    Outcome labels:
        ``"sent"``     — email queued via Gmail.
        ``"dry_run"``  — DRY_RUN; rendered email printed to stdout.
        ``"skipped"``  — no patterns or no verdict candidates; nothing sent.
    """
    digest = build_digest(conn, week_iso, vault_name=vault_name)
    log.info(
        "digest: week=%s patterns=%d candidates=%d",
        digest.week_iso,
        len(digest.sections),
        digest.total_candidates,
    )

    if digest.should_skip:
        log.info(
            "digest: skip (patterns=%d candidates=%d) — no send",
            len(digest.sections),
            digest.total_candidates,
        )
        return "skipped"

    subject = format_subject(digest)
    text_body = render_plain_text(digest)
    html_body = render_html(digest)

    if dry_run:
        print(f"Subject: {subject}\nTo: {recipient}\n")
        print(text_body)
        return "dry_run"

    email_sender.send_email(
        subject=subject,
        to=recipient,
        html_body=html_body,
        text_body=text_body,
    )
    log.info("digest: sent to %s (subject=%r)", recipient, subject)
    return "sent"


# ----------------------------------------------------------------------
# CLI entry-point
# ----------------------------------------------------------------------


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return psycopg.connect(url)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    recipient = os.environ.get("RECIPIENT_EMAIL")
    if not recipient:
        print("ERROR: RECIPIENT_EMAIL is not set", file=sys.stderr)
        return 1

    dry_run = _dry_run_enabled()
    if not dry_run:
        missing = [
            k
            for k in (
                "GMAIL_CLIENT_ID",
                "GMAIL_CLIENT_SECRET",
                "GMAIL_REFRESH_TOKEN",
            )
            if not os.environ.get(k)
        ]
        if missing:
            print(
                f"ERROR: missing Gmail env vars: {', '.join(missing)}",
                file=sys.stderr,
            )
            return 1

    week_iso = os.environ.get(WEEK_ISO_ENV) or current_week_iso()
    vault_name = os.environ.get(VAULT_NAME_ENV) or DEFAULT_VAULT_NAME
    log.info("digest: week_iso=%s dry_run=%s", week_iso, dry_run)

    with _connect() as conn:
        outcome = run(
            conn,
            week_iso=week_iso,
            recipient=recipient,
            dry_run=dry_run,
            vault_name=vault_name,
        )
    log.info("digest: done outcome=%s", outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
