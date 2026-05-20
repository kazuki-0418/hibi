"""Tests for `idea_mining.digest.run` skip semantics (Issue #140).

acceptance criteria:

    対象週の patterns または verdict 付き candidates がゼロのときは
    送信スキップしログのみ残す (workflow は exit 0)
"""
from __future__ import annotations

import idea_mining.digest as digest_module
from idea_mining.digest import run

from tests.idea_mining._digest_fakes import CandidateRow, FakeConn, PatternRow

WEEK = "2026-W21"


def _no_send(monkeypatch) -> list[dict[str, object]]:
    """Replace `email_sender.send_email` with a spy so a skip never sends."""
    calls: list[dict[str, object]] = []

    def fake_send(**kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr(digest_module.email_sender, "send_email", fake_send)
    return calls


def test_run_skips_when_no_patterns_for_week(monkeypatch) -> None:
    """対象週に pattern が 1 件もない → skip."""
    sends = _no_send(monkeypatch)
    conn = FakeConn(
        patterns=[
            # 別週の pattern のみ → 対象週から見ると 0 件。
            PatternRow(
                id="p-other",
                week_iso="2026-W20",
                pain="別週 pain",
                categories=[],
                frequency=10,
                source_diversity=3,
                confidence=0.9,
            ),
        ],
        candidates=[],
    )
    outcome = run(
        conn,
        week_iso=WEEK,
        recipient="kazuki@example.com",
        dry_run=False,
    )
    assert outcome == "skipped"
    assert sends == []


def test_run_skips_when_no_verdict_candidates(monkeypatch) -> None:
    """patterns はあるが verdict 付き candidate が 0 → skip."""
    sends = _no_send(monkeypatch)
    conn = FakeConn(
        patterns=[
            PatternRow(
                id="p-1",
                week_iso=WEEK,
                pain="pain-X",
                categories=[],
                frequency=10,
                source_diversity=3,
                confidence=0.8,
            ),
        ],
        candidates=[
            CandidateRow(
                id=1,
                pattern_id="p-1",
                name="まだ verdict 出てない",
                critic_verdict=None,
            ),
        ],
    )
    outcome = run(
        conn,
        week_iso=WEEK,
        recipient="kazuki@example.com",
        dry_run=False,
    )
    assert outcome == "skipped"
    assert sends == []


def test_run_sends_when_at_least_one_verdict_candidate(monkeypatch) -> None:
    """skip 条件の counter-test: 1 件でも verdict があれば送信する。"""
    sends = _no_send(monkeypatch)
    conn = FakeConn(
        patterns=[
            PatternRow(
                id="p-1",
                week_iso=WEEK,
                pain="pain-X",
                categories=[],
                frequency=10,
                source_diversity=3,
                confidence=0.8,
            ),
        ],
        candidates=[
            CandidateRow(
                id=1,
                pattern_id="p-1",
                name="採用候補",
                critic_verdict="GO",
                one_liner="GO の 1 行",
                generated_at_rank=1,
            ),
        ],
    )
    outcome = run(
        conn,
        week_iso=WEEK,
        recipient="kazuki@example.com",
        dry_run=False,
    )
    assert outcome == "sent"
    assert len(sends) == 1
    payload = sends[0]
    assert payload["to"] == "kazuki@example.com"
    assert payload["subject"] == "[Hibi] 今週のアイデア候補 1 件 (2026-W21)"
    # multipart で plain + html 両方が乗っている。
    assert payload["text_body"] is not None
    assert payload["html_body"] is not None


def test_run_dry_run_prints_and_does_not_send(monkeypatch, capsys) -> None:
    """DRY_RUN: stdout に出力し、Gmail は呼ばない (skip 条件には該当しない)。"""
    sends = _no_send(monkeypatch)
    conn = FakeConn(
        patterns=[
            PatternRow(
                id="p-1",
                week_iso=WEEK,
                pain="pain-Y",
                categories=[],
                frequency=8,
                source_diversity=2,
                confidence=0.7,
            ),
        ],
        candidates=[
            CandidateRow(
                id=2,
                pattern_id="p-1",
                name="dry-run GO",
                critic_verdict="GO",
                one_liner="dry-run 用",
                generated_at_rank=1,
            ),
        ],
    )
    outcome = run(
        conn,
        week_iso=WEEK,
        recipient="kazuki@example.com",
        dry_run=True,
    )
    assert outcome == "dry_run"
    assert sends == []
    captured = capsys.readouterr().out
    assert "[Hibi] 今週のアイデア候補 1 件 (2026-W21)" in captured
    assert "dry-run GO" in captured
