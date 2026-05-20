"""Tests for `idea_mining.ideator` E2E candidate insertion path.

Anthropic / Neon は in-memory fake で代用。Issue #138 acceptance: 1 pattern
あたり 5-10 件の候補を candidates テーブルへ insert する。SQL contract は
INSERT 文字列レベルで確認する。
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from idea_mining.ideator import (
    CLAUDE_MODEL,
    INSERT_CANDIDATE_SQL,
    SELECT_PATTERN_SQL,
    insert_candidates,
    run_for_pattern,
)


PATTERN_ID = "11111111-1111-1111-1111-111111111111"
PATTERN_PAIN = "重複の SaaS 課金がしんどい"

PROFILE_FIXTURE = """\
# User Constraints
- 必須項目: 個人プロジェクト前提

# Negative Examples
## Aesthetic OS
- 理由: コンセプト先行
"""


# ----------------------------------------------------------------------
# Fake psycopg-shaped connection
# ----------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fake_conn: "_FakeConn") -> None:
        self._fake_conn = fake_conn
        self.executed: list[tuple[str, Any]] = []
        self._select_result: list[tuple[Any, ...]] = []
        self.rowcount: int = 0

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        self._fake_conn.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "from patterns" in normalized and "select" in normalized:
            assert isinstance(params, tuple)
            pid = params[0]
            if pid in self._fake_conn.patterns_by_id:
                row = self._fake_conn.patterns_by_id[pid]
                self._select_result = [row]
                self.rowcount = 1
            else:
                self._select_result = []
                self.rowcount = 0
            return
        if "insert into candidates" in normalized:
            assert isinstance(params, dict)
            self._fake_conn.candidates_inserted.append(dict(params))
            self.rowcount = 1
            return
        self.rowcount = 0

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._select_result[0] if self._select_result else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._select_result)

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def __init__(
        self, patterns_by_id: dict[str, tuple[Any, ...]] | None = None
    ) -> None:
        self.patterns_by_id: dict[str, tuple[Any, ...]] = dict(
            patterns_by_id or {}
        )
        self.candidates_inserted: list[dict[str, Any]] = []
        self.executed: list[tuple[str, Any]] = []
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


# ----------------------------------------------------------------------
# Fake Anthropic
# ----------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, text: str, recorder: list[dict[str, Any]]) -> None:
        self._text = text
        self._recorder = recorder

    def create(self, **kwargs: Any) -> Any:
        self._recorder.append(kwargs)

        class _Block:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Resp:
            def __init__(self, blocks: list[_Block]) -> None:
                self.content = blocks

        return _Resp([_Block(self._text)])


class _FakeAnthropic:
    def __init__(self, text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = _FakeMessages(text, self.calls)


# ----------------------------------------------------------------------
# Response builders
# ----------------------------------------------------------------------


def _candidate(name: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "one_liner": f"{name} の 1 行説明",
        "target_user": "個人開発者",
        "monetization": "subscription",
        "llm_moat_conditions": ["workflow", "data"],
        "why_different": "コンセプト先行ではなく実運用ログから始まる",
        "estimated_mvp_hours": 40,
        "killer_use_case": "実運用での反復ログ",
    }
    base.update(overrides)
    return base


def _opus_payload(candidates: list[dict[str, Any]]) -> str:
    return json.dumps({"candidates": candidates}, ensure_ascii=False)


def _make_pattern_row(pattern_id: str = PATTERN_ID) -> tuple[Any, ...]:
    return (pattern_id, PATTERN_PAIN)


# ----------------------------------------------------------------------
# SQL contracts
# ----------------------------------------------------------------------


def test_select_pattern_sql_is_a_safe_param_query() -> None:
    normalized = " ".join(SELECT_PATTERN_SQL.split()).lower()
    assert normalized.startswith("select id, pain from patterns where id = %s")


def test_insert_candidate_sql_lists_all_required_columns() -> None:
    normalized = " ".join(INSERT_CANDIDATE_SQL.split()).lower()
    assert "insert into candidates" in normalized
    for col in (
        "spot_id",
        "pattern_id",
        "name",
        "one_liner",
        "target_user",
        "monetization",
        "llm_moat_conditions",
        "why_different",
        "estimated_mvp_hours",
        "killer_use_case",
    ):
        assert col in normalized, f"INSERT missing column: {col}"


def test_insert_candidate_sql_uses_named_parameters() -> None:
    for placeholder in (
        "%(spot_id)s",
        "%(pattern_id)s",
        "%(name)s",
        "%(monetization)s",
        "%(llm_moat_conditions)s",
    ):
        assert placeholder in INSERT_CANDIDATE_SQL


# ----------------------------------------------------------------------
# insert_candidates
# ----------------------------------------------------------------------


def test_insert_candidates_writes_each_row_and_commits_once() -> None:
    conn = _FakeConn()
    candidates = [
        {
            "name": f"Candidate {i}",
            "one_liner": "1 行",
            "target_user": "個人開発者",
            "monetization": "subscription",
            "llm_moat_conditions": ["workflow", "data"],
            "why_different": "...",
            "estimated_mvp_hours": 40,
            "killer_use_case": "...",
        }
        for i in range(5)
    ]

    inserted = insert_candidates(conn, candidates, pattern_id=PATTERN_ID)  # type: ignore[arg-type]

    assert inserted == 5
    assert len(conn.candidates_inserted) == 5
    assert conn.commits == 1
    # Every row references the input pattern_id.
    assert all(row["pattern_id"] == PATTERN_ID for row in conn.candidates_inserted)
    # spot_id must remain null in Phase 0.
    assert all(row["spot_id"] is None for row in conn.candidates_inserted)


def test_insert_candidates_passes_arrays_as_lists() -> None:
    conn = _FakeConn()
    candidates = [
        {
            "name": "x",
            "one_liner": "y",
            "target_user": "z",
            "monetization": "subscription",
            "llm_moat_conditions": ["workflow", "data", "trust"],
            "why_different": None,
            "estimated_mvp_hours": None,
            "killer_use_case": None,
        }
    ]

    insert_candidates(conn, candidates, pattern_id=PATTERN_ID)  # type: ignore[arg-type]

    assert conn.candidates_inserted[0]["llm_moat_conditions"] == [
        "workflow",
        "data",
        "trust",
    ]


def test_insert_candidates_returns_zero_when_empty_list() -> None:
    conn = _FakeConn()

    inserted = insert_candidates(conn, [], pattern_id=PATTERN_ID)  # type: ignore[arg-type]

    assert inserted == 0
    assert conn.candidates_inserted == []
    assert conn.commits == 0


# ----------------------------------------------------------------------
# run_for_pattern — full path
# ----------------------------------------------------------------------


def test_run_for_pattern_inserts_5_candidates_min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(patterns_by_id={PATTERN_ID: _make_pattern_row()})
    payload = _opus_payload([_candidate(f"Cand-{i}") for i in range(5)])
    client = _FakeAnthropic(text=payload)

    inserted = run_for_pattern(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        pattern_id=PATTERN_ID,
        profile_block=PROFILE_FIXTURE,
    )

    assert inserted == 5
    assert len(conn.candidates_inserted) == 5
    # Opus was called exactly once, with Opus model id.
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == CLAUDE_MODEL


def test_run_for_pattern_inserts_up_to_10_candidates() -> None:
    conn = _FakeConn(patterns_by_id={PATTERN_ID: _make_pattern_row()})
    payload = _opus_payload([_candidate(f"Cand-{i}") for i in range(10)])
    client = _FakeAnthropic(text=payload)

    inserted = run_for_pattern(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        pattern_id=PATTERN_ID,
        profile_block=PROFILE_FIXTURE,
    )

    assert inserted == 10


def test_run_for_pattern_calls_opus_with_profile_in_system_prompt() -> None:
    conn = _FakeConn(patterns_by_id={PATTERN_ID: _make_pattern_row()})
    payload = _opus_payload([_candidate(f"Cand-{i}") for i in range(5)])
    client = _FakeAnthropic(text=payload)

    run_for_pattern(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        pattern_id=PATTERN_ID,
        profile_block=PROFILE_FIXTURE,
    )

    call = client.calls[0]
    assert "必須項目: 個人プロジェクト前提" in call["system"]
    assert "Aesthetic OS" in call["system"]
    # pattern.pain is delivered in the user message.
    user_content = call["messages"][0]["content"]
    assert PATTERN_PAIN in user_content


def test_run_for_pattern_skips_when_pattern_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(patterns_by_id={})  # no rows
    client = _FakeAnthropic(text="(should not be called)")

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(msg: str, **kwargs: Any) -> None:
        captured.append((msg, kwargs))

    from idea_mining import ideator as ideator_mod

    monkeypatch.setattr(
        ideator_mod.sentry_sdk, "capture_message", fake_capture
    )

    inserted = run_for_pattern(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        pattern_id=PATTERN_ID,
        profile_block=PROFILE_FIXTURE,
    )

    assert inserted == 0
    assert client.calls == []
    assert conn.candidates_inserted == []
    assert len(captured) == 1
    assert "pattern not found" in captured[0][0]


def test_run_for_pattern_returns_zero_on_malformed_opus_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(patterns_by_id={PATTERN_ID: _make_pattern_row()})
    client = _FakeAnthropic(text="not JSON at all")

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(msg: str, **kwargs: Any) -> None:
        captured.append((msg, kwargs))

    from idea_mining import ideator as ideator_mod

    monkeypatch.setattr(
        ideator_mod.sentry_sdk, "capture_message", fake_capture
    )

    inserted = run_for_pattern(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        pattern_id=PATTERN_ID,
        profile_block=PROFILE_FIXTURE,
    )

    assert inserted == 0
    assert conn.candidates_inserted == []
    assert len(captured) == 1
    assert "malformed" in captured[0][0].lower()


def test_run_for_pattern_drops_invalid_candidates_but_inserts_valid() -> None:
    conn = _FakeConn(patterns_by_id={PATTERN_ID: _make_pattern_row()})
    payload = _opus_payload(
        [
            _candidate("Good-1"),
            _candidate("Bad-empty-moat", llm_moat_conditions=[]),
            _candidate("Bad-bad-monetization", monetization="ads"),
            _candidate("Good-2"),
            _candidate("Good-3"),
        ]
    )
    client = _FakeAnthropic(text=payload)

    inserted = run_for_pattern(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        pattern_id=PATTERN_ID,
        profile_block=PROFILE_FIXTURE,
    )

    assert inserted == 3
    names = {row["name"] for row in conn.candidates_inserted}
    assert names == {"Good-1", "Good-2", "Good-3"}
