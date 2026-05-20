"""Tests for `idea_mining.critic` E2E adversarial review path.

Anthropic / Neon は in-memory fake で代用。Issue #139 acceptance:

* `candidates.critic_verdict IS NULL` を snapshot 取得し 1 row ずつ Sonnet で
  評価する
* verdict は GO / PENDING / KILL のいずれか、critic_meta は JSONB
* 1 row 1 commit (row-level transaction)
* malformed JSON は sentry capture + warning ログで skip、raise / retry しない
* 'LLM thin wrapper + target self-resolves' 相当 fixture が KILL になる
* prompt 末尾 RUBRIC テキストが Decisions §4 の verbatim と一致する
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from idea_mining.critic import (
    REQUIRED_META_KEYS,
    SELECT_CANDIDATE_IDS_SQL,
    SELECT_CANDIDATE_SQL,
    SONNET_MODEL,
    UPDATE_CRITIC_SQL,
    build_system_prompt,
    build_user_message,
    extract_verdict_and_meta,
    fetch_candidate,
    fetch_candidate_ids,
    parse_sonnet_response,
    run_for_candidate,
    update_critic_verdict,
)
from idea_mining.prompts.critic import SYSTEM_PROMPT_TEMPLATE

PROFILE_FIXTURE = """\
# User Constraints
- 個人プロジェクト前提
- LLM thin wrapper は避ける

# Negative Examples
## Aesthetic OS
- 理由: コンセプト先行 / LLM thin wrapper
"""

# Decisions §4 の RUBRIC テキスト (verbatim contract — このリテラルが prompt
# 末尾と一致しなければ Critic prompt の意味的同一性が崩れる)。
RUBRIC_VERBATIM = (
    "RUBRIC:\n"
    "- 5 Forces: 業界構造 (新規参入 / 代替品 / 供給者 / 買い手 / 競合) を評価\n"
    "- PESTLE: 政治 / 経済 / 社会 / 技術 / 法 / 環境\n"
    "- Pre-Build KILL: 既存 SaaS で 30 分以内に置換できるなら KILL\n"
    "- LLM-Moat 7-cond: (1) 専有データ (2) ワークフロー深さ (3) ネットワーク効果 "
    "(4) 統合密度 (5) コンプライアンス (6) 製造/物流 (7) ブランド/コミュニティ "
    "— 2 つ以上満たさないなら PENDING、いずれも満たさないなら KILL\n"
    "- Killer Scenarios: 3 ヶ月以内に競合大手がこの機能を出した場合の生存率"
)


# ----------------------------------------------------------------------
# Fake psycopg-shaped connection
# ----------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fake_conn: "_FakeConn") -> None:
        self._fake_conn = fake_conn
        self._select_result: list[tuple[Any, ...]] = []
        self.rowcount: int = 0

    def execute(self, sql: str, params: Any = None) -> None:
        self._fake_conn.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()

        if "select id from candidates where critic_verdict is null" in normalized:
            rows = [
                (cid,)
                for cid, row in sorted(self._fake_conn.rows_by_id.items())
                if row.get("critic_verdict") is None
            ]
            self._select_result = rows
            self.rowcount = len(rows)
            return

        if "from candidates where id =" in normalized and "select" in normalized:
            assert isinstance(params, tuple)
            cid = int(params[0])
            row = self._fake_conn.rows_by_id.get(cid)
            if row is None:
                self._select_result = []
                self.rowcount = 0
                return
            self._select_result = [
                (
                    row["id"],
                    row["name"],
                    row.get("one_liner"),
                    row.get("target_user"),
                    row.get("monetization"),
                    row.get("llm_moat_conditions"),
                    row.get("why_different"),
                    row.get("estimated_mvp_hours"),
                    row.get("killer_use_case"),
                )
            ]
            self.rowcount = 1
            return

        if "update candidates" in normalized:
            assert isinstance(params, tuple) and len(params) == 3
            verdict, meta_json, cid = params
            assert isinstance(verdict, str)
            assert isinstance(meta_json, str)
            target = self._fake_conn.rows_by_id.get(int(cid))
            if target is None or target.get("critic_verdict") is not None:
                self.rowcount = 0
                return
            target["critic_verdict"] = verdict
            target["critic_meta"] = json.loads(meta_json)
            self._fake_conn.updates_applied.append(
                {
                    "id": int(cid),
                    "verdict": verdict,
                    "meta": target["critic_meta"],
                }
            )
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
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows_by_id: dict[int, dict[str, Any]] = {}
        for row in rows or []:
            self.rows_by_id[int(row["id"])] = dict(row)
        self.executed: list[tuple[str, Any]] = []
        self.updates_applied: list[dict[str, Any]] = []
        self.commits: int = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


# ----------------------------------------------------------------------
# Fake Anthropic
# ----------------------------------------------------------------------


class _FakeMessages:
    def __init__(
        self,
        recorder: list[dict[str, Any]],
        text_strategy: Any,
    ) -> None:
        self._recorder = recorder
        self._text_strategy = text_strategy

    def create(self, **kwargs: Any) -> Any:
        self._recorder.append(kwargs)
        strategy = self._text_strategy
        if callable(strategy):
            text = strategy(kwargs, len(self._recorder) - 1)
        else:
            text = strategy

        class _Block:
            def __init__(self, t: str) -> None:
                self.text = t

        class _Resp:
            def __init__(self, blocks: list[_Block]) -> None:
                self.content = blocks

        return _Resp([_Block(text)])


class _FakeAnthropic:
    def __init__(self, text_strategy: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = _FakeMessages(self.calls, text_strategy)


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------


def _candidate_row(
    cid: int,
    *,
    name: str = "Some Candidate",
    critic_verdict: str | None = None,
    critic_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "name": name,
        "one_liner": f"{name} の 1 行説明",
        "target_user": "個人開発者",
        "monetization": "subscription",
        "llm_moat_conditions": ["workflow", "data"],
        "why_different": "...",
        "estimated_mvp_hours": 40,
        "killer_use_case": "...",
        "critic_verdict": critic_verdict,
        "critic_meta": critic_meta,
    }


def _critic_payload(
    verdict: str,
    *,
    overrides: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "verdict": verdict,
        "five_forces": {
            "rivalry": "H",
            "new_entrants": "H",
            "substitutes": "H",
            "buyers": "M",
            "suppliers": "L",
        },
        "pestle": {
            "political": "neutral",
            "economic": "headwind",
            "social": "neutral",
            "technological": "tailwind",
            "legal": "neutral",
            "environmental": "neutral",
        },
        "kill_flags": [],
        "llm_moat_conditions": ["workflow"],
        "killer_scenarios": ["Foundation Model update absorbs the feature."],
        "cited_competitors": [],
        "kill_reasons": [],
    }
    if overrides:
        payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


# ----------------------------------------------------------------------
# SQL contracts
# ----------------------------------------------------------------------


def test_select_candidate_ids_sql_filters_null_verdict_only() -> None:
    normalized = " ".join(SELECT_CANDIDATE_IDS_SQL.split()).lower()
    assert normalized.startswith("select id from candidates where critic_verdict is null")


def test_select_candidate_sql_lists_required_columns() -> None:
    normalized = " ".join(SELECT_CANDIDATE_SQL.split()).lower()
    for col in (
        "name",
        "one_liner",
        "target_user",
        "monetization",
        "llm_moat_conditions",
        "why_different",
        "estimated_mvp_hours",
        "killer_use_case",
    ):
        assert col in normalized, f"SELECT missing column: {col}"


def test_update_critic_sql_uses_jsonb_cast_and_null_guard() -> None:
    normalized = " ".join(UPDATE_CRITIC_SQL.split()).lower()
    assert "update candidates" in normalized
    assert "set critic_verdict = %s" in normalized
    assert "critic_meta = %s::jsonb" in normalized
    assert "where id = %s" in normalized
    assert "and critic_verdict is null" in normalized


def test_update_critic_sql_does_not_insert() -> None:
    """Critic must never INSERT — only UPDATE existing candidates."""
    normalized = " ".join(UPDATE_CRITIC_SQL.split()).lower()
    assert "insert" not in normalized


# ----------------------------------------------------------------------
# Prompt contracts
# ----------------------------------------------------------------------


def test_system_prompt_template_has_single_profile_block_placeholder() -> None:
    # Only `{profile_block}` should be a substitution; all other literal
    # braces (in the OUTPUT JSON example) must already be escaped as
    # `{{` / `}}` so that `.format()` does not blow up.
    formatted = SYSTEM_PROMPT_TEMPLATE.format(profile_block="X")
    # Brace-equal-count means escaping was consistent.
    assert formatted.count("{") == formatted.count("}")
    # The replacement landed exactly once.
    assert formatted.count("X") == 1


def test_system_prompt_template_contains_rubric_verbatim() -> None:
    formatted = SYSTEM_PROMPT_TEMPLATE.format(profile_block=PROFILE_FIXTURE)
    assert RUBRIC_VERBATIM in formatted
    # The RUBRIC block sits at (or near) the tail — assert it occurs after
    # the profile block.
    assert formatted.index(RUBRIC_VERBATIM) > formatted.index(PROFILE_FIXTURE)


def test_build_system_prompt_injects_profile_block() -> None:
    prompt = build_system_prompt(PROFILE_FIXTURE)
    assert "個人プロジェクト前提" in prompt
    assert "Aesthetic OS" in prompt
    # And the formatted output equals SYSTEM_PROMPT_TEMPLATE.format(...).
    assert prompt == SYSTEM_PROMPT_TEMPLATE.format(profile_block=PROFILE_FIXTURE)


def test_build_system_prompt_rejects_empty_profile() -> None:
    with pytest.raises(ValueError):
        build_system_prompt("")
    with pytest.raises(ValueError):
        build_system_prompt("   \n  ")


def test_build_user_message_contains_candidate_name() -> None:
    cand = _candidate_row(7, name="Some Candidate")
    msg = build_user_message(cand)
    assert "Some Candidate" in msg


# ----------------------------------------------------------------------
# Response parsing
# ----------------------------------------------------------------------


def test_parse_sonnet_response_pulls_json_object() -> None:
    raw = 'preamble \n{"verdict": "KILL"}\n trailing'
    out = parse_sonnet_response(raw)
    assert out == {"verdict": "KILL"}


def test_parse_sonnet_response_raises_on_malformed_json() -> None:
    with pytest.raises(ValueError):
        parse_sonnet_response("not JSON at all")


def test_extract_verdict_and_meta_pulls_required_keys() -> None:
    parsed = json.loads(_critic_payload("GO"))
    verdict, meta = extract_verdict_and_meta(parsed)
    assert verdict == "GO"
    for key in REQUIRED_META_KEYS:
        assert key in meta


def test_extract_verdict_and_meta_uppercases_verdict() -> None:
    parsed = {"verdict": "kill"}
    verdict, _ = extract_verdict_and_meta(parsed)
    assert verdict == "KILL"


def test_extract_verdict_and_meta_rejects_unknown_verdict() -> None:
    with pytest.raises(ValueError):
        extract_verdict_and_meta({"verdict": "DUNNO"})


def test_extract_verdict_and_meta_rejects_missing_verdict() -> None:
    with pytest.raises(ValueError):
        extract_verdict_and_meta({"other_field": "x"})


# ----------------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------------


def test_fetch_candidate_ids_returns_only_null_verdict_rows() -> None:
    conn = _FakeConn(
        rows=[
            _candidate_row(1),
            _candidate_row(2, critic_verdict="GO"),
            _candidate_row(3),
        ]
    )

    ids = fetch_candidate_ids(conn)  # type: ignore[arg-type]

    assert ids == [1, 3]


def test_fetch_candidate_returns_none_for_missing() -> None:
    conn = _FakeConn()

    out = fetch_candidate(conn, 999)  # type: ignore[arg-type]

    assert out is None


def test_update_critic_verdict_commits_per_row() -> None:
    conn = _FakeConn(rows=[_candidate_row(1)])

    rowcount = update_critic_verdict(
        conn,  # type: ignore[arg-type]
        candidate_id=1,
        verdict="GO",
        meta={"five_forces": {"rivalry": "L"}, "kill_reasons": []},
    )

    assert rowcount == 1
    assert conn.commits == 1
    assert conn.rows_by_id[1]["critic_verdict"] == "GO"
    assert conn.rows_by_id[1]["critic_meta"] == {
        "five_forces": {"rivalry": "L"},
        "kill_reasons": [],
    }


def test_update_critic_verdict_noops_when_already_verdicted() -> None:
    """Defense-in-depth: UPDATE WHERE critic_verdict IS NULL must skip rows
    already marked. (Snapshot iteration guarantees no double-UPDATE within
    the same batch, but this row-level guard catches concurrency too.)"""
    conn = _FakeConn(rows=[_candidate_row(1, critic_verdict="KILL")])

    rowcount = update_critic_verdict(
        conn,  # type: ignore[arg-type]
        candidate_id=1,
        verdict="GO",
        meta={},
    )

    assert rowcount == 0
    assert conn.rows_by_id[1]["critic_verdict"] == "KILL"


# ----------------------------------------------------------------------
# run_for_candidate — full path
# ----------------------------------------------------------------------


def test_run_for_candidate_updates_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(rows=[_candidate_row(1, name="Good Idea")])
    client = _FakeAnthropic(_critic_payload("GO"))

    ok = run_for_candidate(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        candidate_id=1,
        profile=PROFILE_FIXTURE,
    )

    assert ok is True
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == SONNET_MODEL
    assert conn.commits == 1
    assert conn.rows_by_id[1]["critic_verdict"] == "GO"
    meta = conn.rows_by_id[1]["critic_meta"]
    assert isinstance(meta, dict)
    for key in REQUIRED_META_KEYS:
        assert key in meta


def test_run_for_candidate_skips_when_candidate_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    client = _FakeAnthropic("(should not be called)")

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(msg: str, **kwargs: Any) -> None:
        captured.append((msg, kwargs))

    from idea_mining import critic as critic_mod

    monkeypatch.setattr(
        critic_mod.sentry_sdk, "capture_message", fake_capture
    )

    ok = run_for_candidate(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        candidate_id=99,
        profile=PROFILE_FIXTURE,
    )

    assert ok is False
    assert client.calls == []
    assert conn.commits == 0
    assert len(captured) == 1
    assert "not found" in captured[0][0]


def test_run_for_candidate_skips_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(rows=[_candidate_row(1)])
    client = _FakeAnthropic("not JSON at all")

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(msg: str, **kwargs: Any) -> None:
        captured.append((msg, kwargs))

    from idea_mining import critic as critic_mod

    monkeypatch.setattr(
        critic_mod.sentry_sdk, "capture_message", fake_capture
    )

    ok = run_for_candidate(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        candidate_id=1,
        profile=PROFILE_FIXTURE,
    )

    assert ok is False
    assert conn.commits == 0
    assert conn.rows_by_id[1]["critic_verdict"] is None
    assert len(captured) == 1
    assert "malformed" in captured[0][0].lower()


def test_run_for_candidate_skips_on_invalid_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(rows=[_candidate_row(1)])
    client = _FakeAnthropic('{"verdict": "DUNNO"}')

    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(msg: str, **kwargs: Any) -> None:
        captured.append((msg, kwargs))

    from idea_mining import critic as critic_mod

    monkeypatch.setattr(
        critic_mod.sentry_sdk, "capture_message", fake_capture
    )

    ok = run_for_candidate(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        candidate_id=1,
        profile=PROFILE_FIXTURE,
    )

    assert ok is False
    assert conn.rows_by_id[1]["critic_verdict"] is None
    assert len(captured) == 1


# ----------------------------------------------------------------------
# Row-level commit — one bad row should not roll back others
# ----------------------------------------------------------------------


def test_batch_row_level_commit_isolates_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run 3 candidates; the middle one returns malformed JSON. The first
    and third UPDATEs must remain committed even though the middle skipped.
    """
    conn = _FakeConn(
        rows=[
            _candidate_row(1, name="A"),
            _candidate_row(2, name="B"),
            _candidate_row(3, name="C"),
        ]
    )

    # Per-call mapping by candidate name embedded in the user message
    # ("name: 'A'" / "name: 'B'" / "name: 'C'").
    def text_strategy(kwargs: dict[str, Any], _i: int) -> str:
        user_content = kwargs["messages"][0]["content"]
        if "'A'" in user_content:
            return _critic_payload("GO")
        if "'B'" in user_content:
            return "not JSON at all"
        if "'C'" in user_content:
            return _critic_payload("KILL")
        raise AssertionError(f"unexpected user content: {user_content!r}")

    client = _FakeAnthropic(text_strategy)

    captured: list[str] = []

    def fake_capture(msg: str, **_kwargs: Any) -> None:
        captured.append(msg)

    from idea_mining import critic as critic_mod

    monkeypatch.setattr(
        critic_mod.sentry_sdk, "capture_message", fake_capture
    )

    ids = fetch_candidate_ids(conn)  # type: ignore[arg-type]
    assert ids == [1, 2, 3]

    results: list[bool] = []
    for cid in ids:
        results.append(
            run_for_candidate(
                conn,  # type: ignore[arg-type]
                client,  # type: ignore[arg-type]
                candidate_id=cid,
                profile=PROFILE_FIXTURE,
            )
        )

    assert results == [True, False, True]
    # 2 successful UPDATEs → 2 commits. The skipped row never reached the
    # UPDATE/commit step.
    assert conn.commits == 2
    assert conn.rows_by_id[1]["critic_verdict"] == "GO"
    assert conn.rows_by_id[2]["critic_verdict"] is None  # untouched
    assert conn.rows_by_id[3]["critic_verdict"] == "KILL"
    assert len(captured) == 1
    assert "malformed" in captured[0].lower()


def test_batch_only_processes_null_verdict_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rows with verdict already set are excluded from the snapshot, so
    Sonnet is never invoked for them and they are not re-UPDATEd."""
    conn = _FakeConn(
        rows=[
            _candidate_row(1, name="Pending Row"),
            _candidate_row(2, name="Already Verdicted", critic_verdict="GO"),
            _candidate_row(3, name="Another Pending"),
        ]
    )
    client = _FakeAnthropic(_critic_payload("PENDING"))

    ids = fetch_candidate_ids(conn)  # type: ignore[arg-type]
    assert ids == [1, 3]
    for cid in ids:
        run_for_candidate(
            conn,  # type: ignore[arg-type]
            client,  # type: ignore[arg-type]
            candidate_id=cid,
            profile=PROFILE_FIXTURE,
        )

    # Sonnet was called exactly twice (once per pending row).
    assert len(client.calls) == 2
    # The already-verdicted row was not touched.
    assert conn.rows_by_id[2]["critic_verdict"] == "GO"
    # Both pending rows are now verdicted.
    assert conn.rows_by_id[1]["critic_verdict"] == "PENDING"
    assert conn.rows_by_id[3]["critic_verdict"] == "PENDING"


# ----------------------------------------------------------------------
# Aesthetic-OS-style KILL fixture
# ----------------------------------------------------------------------


def test_llm_thin_wrapper_target_self_resolves_is_killed() -> None:
    """The Critic must KILL ideas that are LLM thin wrappers whose target
    user can self-resolve the pain with the raw LLM. The verdict and the
    cited reasons must land in critic_meta.

    The test fixture forces Sonnet's response to KILL with explicit
    competitors + kill_reasons; we only verify that the Critic stores
    them in critic_meta exactly as returned (Decisions §B output schema).
    """
    conn = _FakeConn(
        rows=[
            _candidate_row(
                42,
                name="GPT-Backed Note Renamer",
            )
        ]
    )
    kill_payload = _critic_payload(
        "KILL",
        overrides={
            "verdict": "KILL",
            "kill_flags": ["llm_thin_wrapper", "target_self_resolves"],
            "llm_moat_conditions": [],
            "cited_competitors": ["ChatGPT", "Claude.ai", "Notion AI"],
            "kill_reasons": [
                "LLM thin wrapper — target user can paste the same prompt into ChatGPT.",
                "Target user already self-resolves with vanilla ChatGPT free tier.",
            ],
            "killer_scenarios": [
                "Foundation Model update absorbs note renaming as a built-in."
            ],
        },
    )
    client = _FakeAnthropic(kill_payload)

    ok = run_for_candidate(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        candidate_id=42,
        profile=PROFILE_FIXTURE,
    )

    assert ok is True
    row = conn.rows_by_id[42]
    assert row["critic_verdict"] == "KILL"
    meta = row["critic_meta"]
    assert isinstance(meta, dict)
    assert meta["cited_competitors"] == ["ChatGPT", "Claude.ai", "Notion AI"]
    assert any(
        "thin wrapper" in r.lower() for r in meta["kill_reasons"]
    ), meta["kill_reasons"]
    assert any(
        "self-resolve" in r.lower() for r in meta["kill_reasons"]
    ), meta["kill_reasons"]
    assert "llm_thin_wrapper" in meta["kill_flags"]
    assert "target_self_resolves" in meta["kill_flags"]


# ----------------------------------------------------------------------
# Anthropic call args — profile + RUBRIC must land in system prompt
# ----------------------------------------------------------------------


def test_sonnet_call_carries_profile_block_and_rubric() -> None:
    conn = _FakeConn(rows=[_candidate_row(1)])
    client = _FakeAnthropic(_critic_payload("PENDING"))

    run_for_candidate(
        conn,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        candidate_id=1,
        profile=PROFILE_FIXTURE,
    )

    call = client.calls[0]
    assert "個人プロジェクト前提" in call["system"]
    assert "Aesthetic OS" in call["system"]
    assert RUBRIC_VERBATIM in call["system"]
    assert call["model"] == SONNET_MODEL
