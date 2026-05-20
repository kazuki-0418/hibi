"""Tests for digest DB query layer (Issue #140).

* `fetch_top_patterns` は ``week_iso`` で絞り、``frequency`` 降順で最大 3 件
  返す
* `fetch_verdict_candidates` は ``critic_verdict IS NOT NULL`` の行のみ返す
* `_trim_for_display` が GO 2 件 + KILL 1 件にトリムする
"""
from __future__ import annotations

import pytest

from idea_mining.digest import (
    MAX_GO_PER_PATTERN,
    MAX_KILL_PER_PATTERN,
    TOP_PATTERNS,
    Candidate,
    _trim_for_display,
    build_digest,
    fetch_top_patterns,
    fetch_verdict_candidates,
)

from tests.idea_mining._digest_fakes import CandidateRow, FakeConn, PatternRow

WEEK = "2026-W21"
OTHER_WEEK = "2026-W20"


@pytest.fixture
def populated_conn() -> FakeConn:
    return FakeConn(
        patterns=[
            PatternRow(
                id="00000000-0000-0000-0000-00000000000a",
                week_iso=WEEK,
                pain="低 frequency pattern",
                categories=["cat1"],
                frequency=4,
                source_diversity=2,
                confidence=0.6,
            ),
            PatternRow(
                id="00000000-0000-0000-0000-00000000000b",
                week_iso=WEEK,
                pain="高 frequency pattern",
                categories=["cat2"],
                frequency=12,
                source_diversity=4,
                confidence=0.9,
            ),
            PatternRow(
                id="00000000-0000-0000-0000-00000000000c",
                week_iso=WEEK,
                pain="中 frequency pattern",
                categories=["cat3"],
                frequency=8,
                source_diversity=3,
                confidence=0.7,
            ),
            PatternRow(
                id="00000000-0000-0000-0000-00000000000d",
                week_iso=WEEK,
                pain="4 番目 pattern (top 3 で切られる)",
                categories=[],
                frequency=3,
                source_diversity=2,
                confidence=0.5,
            ),
            # 別週の pattern は混入してはいけない。
            PatternRow(
                id="00000000-0000-0000-0000-00000000000e",
                week_iso=OTHER_WEEK,
                pain="別週",
                categories=[],
                frequency=100,
                source_diversity=10,
                confidence=1.0,
            ),
        ],
        candidates=[
            # 高 frequency (b) — GO 3 件 + KILL 2 件 + PENDING 1 件 + 未 verdict 1 件
            CandidateRow(
                id=1,
                pattern_id="00000000-0000-0000-0000-00000000000b",
                name="GO-old",
                critic_verdict="GO",
                generated_at_rank=1,
            ),
            CandidateRow(
                id=2,
                pattern_id="00000000-0000-0000-0000-00000000000b",
                name="GO-mid",
                critic_verdict="GO",
                generated_at_rank=2,
            ),
            CandidateRow(
                id=3,
                pattern_id="00000000-0000-0000-0000-00000000000b",
                name="GO-new",
                critic_verdict="GO",
                generated_at_rank=3,
            ),
            CandidateRow(
                id=4,
                pattern_id="00000000-0000-0000-0000-00000000000b",
                name="KILL-old",
                critic_verdict="KILL",
                generated_at_rank=1,
                critic_meta={"kill_reasons": ["old reason"]},
            ),
            CandidateRow(
                id=5,
                pattern_id="00000000-0000-0000-0000-00000000000b",
                name="KILL-new",
                critic_verdict="KILL",
                generated_at_rank=3,
                critic_meta={"kill_reasons": ["new reason"]},
            ),
            CandidateRow(
                id=6,
                pattern_id="00000000-0000-0000-0000-00000000000b",
                name="PENDING",
                critic_verdict="PENDING",
                generated_at_rank=3,
            ),
            CandidateRow(
                id=7,
                pattern_id="00000000-0000-0000-0000-00000000000b",
                name="未 verdict",
                critic_verdict=None,
                generated_at_rank=3,
            ),
        ],
    )


def test_fetch_top_patterns_filters_week_and_orders_by_frequency_desc(
    populated_conn: FakeConn,
) -> None:
    patterns = fetch_top_patterns(populated_conn, WEEK)
    assert len(patterns) == TOP_PATTERNS == 3
    # 別週は除外。
    pains = [p.pain for p in patterns]
    assert "別週" not in pains
    # frequency DESC
    freqs = [p.frequency for p in patterns]
    assert freqs == sorted(freqs, reverse=True)
    assert freqs == [12, 8, 4]


def test_fetch_verdict_candidates_filters_null_verdict(
    populated_conn: FakeConn,
) -> None:
    candidates = fetch_verdict_candidates(
        populated_conn, "00000000-0000-0000-0000-00000000000b"
    )
    names = [c.name for c in candidates]
    assert "未 verdict" not in names
    # PENDING は除外しない (NOT NULL のみが条件)。
    assert "PENDING" in names
    # 全候補 verdict が GO / PENDING / KILL のいずれか。
    assert all(c.critic_verdict in {"GO", "PENDING", "KILL"} for c in candidates)


def test_fetch_verdict_candidates_orders_newest_first(
    populated_conn: FakeConn,
) -> None:
    candidates = fetch_verdict_candidates(
        populated_conn, "00000000-0000-0000-0000-00000000000b"
    )
    go_names = [c.name for c in candidates if c.critic_verdict == "GO"]
    # 新しい順 (generated_at DESC, id DESC) で並んでいる。
    assert go_names == ["GO-new", "GO-mid", "GO-old"]
    kill_names = [c.name for c in candidates if c.critic_verdict == "KILL"]
    assert kill_names == ["KILL-new", "KILL-old"]


def _mk_candidate(name: str, verdict: str) -> Candidate:
    return Candidate(
        id=hash(name) & 0xFFFFFFF,
        name=name,
        one_liner=None,
        target_user=None,
        monetization=None,
        why_different=None,
        killer_use_case=None,
        critic_verdict=verdict,
        kill_reasons=[],
    )


def test_trim_for_display_caps_go_at_two_and_kill_at_one() -> None:
    candidates = [
        _mk_candidate("g1", "GO"),
        _mk_candidate("g2", "GO"),
        _mk_candidate("g3", "GO"),
        _mk_candidate("k1", "KILL"),
        _mk_candidate("k2", "KILL"),
        _mk_candidate("p1", "PENDING"),
    ]
    go, kill = _trim_for_display(candidates)
    assert len(go) == MAX_GO_PER_PATTERN == 2
    assert [c.name for c in go] == ["g1", "g2"]
    assert len(kill) == MAX_KILL_PER_PATTERN == 1
    assert [c.name for c in kill] == ["k1"]


def test_build_digest_links_candidates_to_each_pattern(
    populated_conn: FakeConn,
) -> None:
    digest = build_digest(populated_conn, WEEK)
    # 3 patterns 全部含まれる (verdict 候補がゼロでも sections に積む)。
    assert len(digest.sections) == 3
    # 高 frequency pattern の section に candidates が乗っている。
    top = digest.sections[0]
    assert top.pattern.pain == "高 frequency pattern"
    assert [c.name for c in top.go_candidates] == ["GO-new", "GO-mid"]
    assert [c.name for c in top.kill_candidates] == ["KILL-new"]
    # KILL の理由は critic_meta から取れている。
    assert top.kill_candidates[0].kill_reasons == ["new reason"]
    # candidate-less pattern も section に乗っている (本文では「verdict 候補
    # なし」表示)。
    others = digest.sections[1:]
    assert all(s.go_candidates == [] and s.kill_candidates == [] for s in others)
