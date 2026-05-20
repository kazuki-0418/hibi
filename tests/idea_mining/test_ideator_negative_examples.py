"""Tests for `idea_mining.ideator` negative-examples enforcement.

Issue #138 acceptance: Aesthetic OS と一致または近似する候補が出ないこと
(negative-examples テストで保証)。

prompt 側に negative-examples を貼っても Opus が稀にすり抜けるため、Python
側で `name` / `one_liner` への単純な substring フィルタを最終ゲートとして
持つ。本テストは、(a) extract_negative_example_names が profile から H2
見出しを拾うこと、(b) validate_candidate が一致候補を reject すること、
(c) run_for_pattern が混在 mock 応答を捌くことを検証する。
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from idea_mining.ideator import (
    extract_negative_example_names,
    run_for_pattern,
    validate_candidate,
)


PATTERN_ID = "22222222-2222-2222-2222-222222222222"
PATTERN_PAIN = "個人開発のアイデアが汎用 AI ニュースリーダー化しがち"

PROFILE_WITH_AESTHETIC_OS = """\
# User Constraints

- 必須項目: 個人プロジェクト前提で運用できること
- 学習信号はクリックのみ

# Negative Examples

## Aesthetic OS
- 理由: コンセプトが先行し、実運用での学習信号が貧弱

## Vibe Reader
- 理由: 汎用ニュースリーダー化、差別化が薄い
"""


# ----------------------------------------------------------------------
# Negative-name extraction
# ----------------------------------------------------------------------


def test_extract_returns_h2_under_negative_examples_heading() -> None:
    names = extract_negative_example_names(PROFILE_WITH_AESTHETIC_OS)

    assert "Aesthetic OS" in names
    assert "Vibe Reader" in names


def test_extract_ignores_h2_under_user_constraints_section() -> None:
    profile = """\
# User Constraints
## 必須項目
- foo

# Negative Examples
## Aesthetic OS
- 理由: bar
"""

    names = extract_negative_example_names(profile)

    assert "必須項目" not in names
    assert "Aesthetic OS" in names


def test_extract_returns_empty_when_no_negative_examples_section() -> None:
    profile = "# User Constraints\n- foo\n"

    names = extract_negative_example_names(profile)

    assert names == []


# ----------------------------------------------------------------------
# validate_candidate against negative-examples
# ----------------------------------------------------------------------


def _good_candidate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Spotline",
        "one_liner": "ローカル現場の B2B micro-SaaS",
        "target_user": "個人運送事業者",
        "monetization": "subscription",
        "llm_moat_conditions": ["workflow", "data"],
        "why_different": "実運用ログから始まる",
        "estimated_mvp_hours": 40,
        "killer_use_case": "請求書を半自動で締める",
    }
    base.update(overrides)
    return base


def test_rejects_candidate_whose_name_is_a_negative_example() -> None:
    out, reason = validate_candidate(
        _good_candidate(name="Aesthetic OS"),
        negative_names=["Aesthetic OS"],
    )

    assert out is None
    assert reason is not None
    assert "negative-example" in reason


def test_rejects_candidate_with_case_insensitive_match() -> None:
    out, reason = validate_candidate(
        _good_candidate(name="aesthetic os"),
        negative_names=["Aesthetic OS"],
    )

    assert out is None
    assert reason is not None


def test_rejects_candidate_when_one_liner_contains_negative_example_name() -> None:
    out, reason = validate_candidate(
        _good_candidate(
            name="MoodKit",
            one_liner="An Aesthetic OS-style mood archive for indies",
        ),
        negative_names=["Aesthetic OS"],
    )

    assert out is None
    assert reason is not None
    assert "Aesthetic OS" in reason


def test_accepts_candidate_when_negative_examples_block_is_empty() -> None:
    out, reason = validate_candidate(
        _good_candidate(name="Aesthetic OS"),
        negative_names=[],
    )

    # With no guards configured, the substring filter is bypassed.
    # (The prompt is the primary defense; this only confirms the gate is gated.)
    assert reason is None
    assert out is not None


def test_accepts_unrelated_candidate_when_guards_active() -> None:
    out, reason = validate_candidate(
        _good_candidate(name="Spotline"),
        negative_names=["Aesthetic OS", "Vibe Reader"],
    )

    assert reason is None
    assert out is not None


# ----------------------------------------------------------------------
# run_for_pattern E2E with negative-example mixed into the mock response
# ----------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fake_conn: "_FakeConn") -> None:
        self._fake_conn = fake_conn
        self._select_result: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        normalized = " ".join(sql.split()).lower()
        if "from patterns" in normalized:
            assert isinstance(params, tuple)
            pid = params[0]
            if pid in self._fake_conn.patterns_by_id:
                self._select_result = [self._fake_conn.patterns_by_id[pid]]
            else:
                self._select_result = []
            return
        if "insert into candidates" in normalized:
            assert isinstance(params, dict)
            self._fake_conn.candidates_inserted.append(dict(params))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._select_result[0] if self._select_result else None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def __init__(self, patterns_by_id: dict[str, tuple[Any, ...]]) -> None:
        self.patterns_by_id = patterns_by_id
        self.candidates_inserted: list[dict[str, Any]] = []
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


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


def _candidate(name: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "name": name,
        "one_liner": f"{name} 1-liner",
        "target_user": "個人開発者",
        "monetization": "subscription",
        "llm_moat_conditions": ["workflow", "data"],
        "why_different": "実運用ログ駆動",
        "estimated_mvp_hours": 40,
        "killer_use_case": "...",
    }
    base.update(overrides)
    return base


def test_run_for_pattern_drops_aesthetic_os_lookalike_from_opus_response() -> None:
    conn = _FakeConn(patterns_by_id={PATTERN_ID: (PATTERN_ID, PATTERN_PAIN)})
    payload = json.dumps(
        {
            "candidates": [
                _candidate("Spotline"),
                _candidate("Aesthetic OS"),  # exact match to negative example
                _candidate(
                    "MoodArchive",
                    one_liner="An Aesthetic OS-shaped archive",
                ),
                _candidate("Spotline-PRO"),
                _candidate("Vibe Reader"),  # second negative example
                _candidate("Spotline-X"),
            ]
        },
        ensure_ascii=False,
    )
    client = _FakeAnthropic(text=payload)

    inserted = run_for_pattern(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        pattern_id=PATTERN_ID,
        profile_block=PROFILE_WITH_AESTHETIC_OS,
    )

    names = {row["name"] for row in conn.candidates_inserted}
    assert "Aesthetic OS" not in names
    assert "Vibe Reader" not in names
    assert "MoodArchive" not in names  # one_liner-side match
    assert {"Spotline", "Spotline-PRO", "Spotline-X"} <= names
    assert inserted == 3
