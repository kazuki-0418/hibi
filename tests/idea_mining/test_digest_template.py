"""Tests for digest HTML / plain text renderers (Issue #140).

3 ケースを検証する:

* GO+KILL 混在 (正常系) — HTML / text 両方に GO 名 / KILL 名 + 理由が出る
* 空週 — レンダリングは可能だが ``should_skip`` が True で配信スキップになる
* verdict 未付与のみ — 同上 (KILL 理由なし表示は呼び出されない)
"""
from __future__ import annotations

from idea_mining.digest import (
    Candidate,
    Digest,
    DigestSection,
    Pattern,
    build_digest,
    format_subject,
    render_html,
    render_plain_text,
)

from tests.idea_mining._digest_fakes import CandidateRow, FakeConn, PatternRow

WEEK = "2026-W21"


def _pattern(
    id_: str, *, pain: str = "テスト pain", frequency: int = 10
) -> Pattern:
    return Pattern(
        id=id_,
        pain=pain,
        categories=["dev"],
        frequency=frequency,
        source_diversity=3,
        confidence=0.8,
    )


def _go(name: str, one_liner: str = "GO 候補の説明") -> Candidate:
    return Candidate(
        id=hash(name) & 0xFFFFFFF,
        name=name,
        one_liner=one_liner,
        target_user="個人開発者",
        monetization="subscription",
        why_different=None,
        killer_use_case=None,
        critic_verdict="GO",
        kill_reasons=[],
    )


def _kill(name: str, reasons: list[str]) -> Candidate:
    return Candidate(
        id=hash(name) & 0xFFFFFFF,
        name=name,
        one_liner="KILL 候補の説明",
        target_user=None,
        monetization=None,
        why_different=None,
        killer_use_case=None,
        critic_verdict="KILL",
        kill_reasons=reasons,
    )


# ----------------------------------------------------------------------
# Case 1: GO + KILL 混在
# ----------------------------------------------------------------------


def test_render_html_and_text_contain_go_and_kill_with_reason() -> None:
    digest = Digest(
        week_iso=WEEK,
        sections=[
            DigestSection(
                pattern=_pattern("p-1", pain="字幕取得が不安定", frequency=12),
                obsidian_url=(
                    "obsidian://open?vault=Obsidan-workspace"
                    "&file=10_projects/hibi/idea-mining/patterns/"
                    "2026-W21/x.md"
                ),
                go_candidates=[
                    _go("GO-α", one_liner="α の 1 行価値"),
                    _go("GO-β"),
                ],
                kill_candidates=[
                    _kill("KILL-γ", reasons=["既存 SaaS で 30 分以内に置換可能"])
                ],
            )
        ],
    )
    assert digest.total_candidates == 3

    subject = format_subject(digest)
    assert subject == "[Hibi] 今週のアイデア候補 3 件 (2026-W21)"

    html_body = render_html(digest)
    text_body = render_plain_text(digest)

    # 件名と pattern pain が両 part に出る。
    assert "字幕取得が不安定" in html_body
    assert "字幕取得が不安定" in text_body

    # GO / KILL ラベル + 候補名が両 part に出る。
    for fragment in ("GO", "KILL", "GO-α", "GO-β", "KILL-γ"):
        assert fragment in html_body
        assert fragment in text_body

    # KILL 理由は両 part で表示。
    assert "既存 SaaS で 30 分以内に置換可能" in html_body
    assert "既存 SaaS で 30 分以内に置換可能" in text_body

    # Vault 直リンクが両 part に含まれる。
    assert "obsidian://open?vault=Obsidan-workspace" in text_body
    # HTML 側は href 内に乗る (& は &amp; に escape されている)。
    assert "obsidian://open?vault=Obsidan-workspace" in html_body
    assert "&amp;file=" in html_body

    # 装飾レイヤ: saturated color / 絵文字を避ける (design-system 準拠)。
    assert "rgb(255" not in html_body  # 鮮色 RGB を直書きしていない
    assert "🟢" not in html_body and "🔴" not in html_body
    assert "🟢" not in text_body and "🔴" not in text_body


# ----------------------------------------------------------------------
# Case 2: 空週 (patterns 0)
# ----------------------------------------------------------------------


def test_empty_week_digest_should_skip_and_renders_safely() -> None:
    digest = Digest(week_iso=WEEK, sections=[])
    assert digest.total_candidates == 0
    assert digest.should_skip is True

    # 念のため、render 関数自体は (呼ばれても) 例外で落ちない。
    text_body = render_plain_text(digest)
    assert WEEK in text_body
    html_body = render_html(digest)
    assert WEEK in html_body


# ----------------------------------------------------------------------
# Case 3: verdict 未付与のみ
# ----------------------------------------------------------------------


def test_only_unverdicted_candidates_skip_but_pattern_rendered_empty() -> None:
    """3 patterns あっても verdict 候補ゼロなら skip 判定。

    ただし render 自体は落ちず、各 section に「verdict 付き候補なし」相当
    の文言が出ていることを確認する。
    """
    conn = FakeConn(
        patterns=[
            PatternRow(
                id="p-1",
                week_iso=WEEK,
                pain="pain-A",
                categories=[],
                frequency=10,
                source_diversity=2,
                confidence=0.8,
            ),
            PatternRow(
                id="p-2",
                week_iso=WEEK,
                pain="pain-B",
                categories=[],
                frequency=5,
                source_diversity=2,
                confidence=0.6,
            ),
        ],
        candidates=[
            # critic_verdict=None → fetch_verdict_candidates でフィルタされる
            CandidateRow(
                id=10,
                pattern_id="p-1",
                name="未 verdict 候補",
                critic_verdict=None,
            ),
        ],
    )
    digest = build_digest(conn, WEEK)
    # patterns は 2 件、candidates は ゼロ。
    assert len(digest.sections) == 2
    assert digest.total_candidates == 0
    assert digest.should_skip is True

    text_body = render_plain_text(digest)
    html_body = render_html(digest)

    # 各 section に「verdict 付き候補なし」表記が出る (本文に登場すること)。
    assert text_body.count("verdict 付き候補なし") == 2
    assert html_body.count("verdict 付き候補なし") == 2

    # pattern pain は両 part に。
    for fragment in ("pain-A", "pain-B"):
        assert fragment in text_body
        assert fragment in html_body
