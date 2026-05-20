"""Tests for `idea_mining.extractor` (voices → patterns via Haiku).

External services (Anthropic / Neon / Sentry) は全部モック。実 Haiku は
叩かない。DB は in-memory fake で代用し、SQL contract (ON CONFLICT
(week_iso, pain) DO UPDATE) は SQL 文字列レベルで確認する。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from idea_mining import extractor as extractor_mod
from idea_mining.extractor import (
    CLAUDE_MODEL,
    LOW_DIVERSITY_CONFIDENCE_CAP,
    MIN_FREQUENCY,
    UPSERT_PATTERN_SQL,
    current_week_iso,
    filter_and_clamp,
    parse_haiku_response,
    run_once,
    upsert_patterns,
)
from idea_mining.prompts.extractor import SYSTEM_PROMPT

REPO_ROOT = Path(__file__).resolve().parents[2]

VOICE_ID_1 = "11111111-1111-1111-1111-111111111111"
VOICE_ID_2 = "22222222-2222-2222-2222-222222222222"
VOICE_ID_3 = "33333333-3333-3333-3333-333333333333"
ALL_VOICE_IDS = {VOICE_ID_1, VOICE_ID_2, VOICE_ID_3}


# ----------------------------------------------------------------------
# Fake DB infra (in-memory psycopg-shaped conn)
# ----------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fake_conn: "_FakeConn") -> None:
        self._fake_conn = fake_conn
        self.executed: list[tuple[str, dict[str, Any] | tuple[Any, ...] | None]] = []
        self.rowcount: int = 0
        self._select_result: list[tuple[Any, ...]] = []

    def execute(
        self, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None
    ) -> None:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select"):
            self._select_result = list(self._fake_conn.voices_rows)
            self.rowcount = len(self._select_result)
            return
        if "insert into patterns" in normalized:
            assert isinstance(params, dict)
            key = (params["week_iso"], params["pain"])
            row = {
                "week_iso": params["week_iso"],
                "pain": params["pain"],
                "categories": list(params["categories"]),
                "frequency": params["frequency"],
                "source_diversity": params["source_diversity"],
                "representative_voices": list(params["representative_voices"]),
                "confidence": params["confidence"],
                "meta": params["meta"],
            }
            if key in self._fake_conn.patterns_by_key:
                self._fake_conn.patterns_by_key[key].update(row)
                self._fake_conn.update_count += 1
            else:
                self._fake_conn.patterns_by_key[key] = row
                self._fake_conn.insert_count += 1
            self.rowcount = 1
            return
        self.rowcount = 0

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._select_result)

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def __init__(self, voices_rows: list[tuple[Any, ...]] | None = None) -> None:
        self.voices_rows: list[tuple[Any, ...]] = list(voices_rows or [])
        self.patterns_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        self.insert_count = 0
        self.update_count = 0
        self.commits = 0
        self._last_cursor: _FakeCursor | None = None

    def cursor(self) -> _FakeCursor:
        cur = _FakeCursor(self)
        self._last_cursor = cur
        return cur

    def commit(self) -> None:
        self.commits += 1


# ----------------------------------------------------------------------
# Haiku response builders
# ----------------------------------------------------------------------


def _pattern(
    *,
    pain: str,
    frequency: int = 3,
    source_diversity: int = 2,
    representative_voices: list[str] | None = None,
    confidence: float = 0.8,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "pain": pain,
        "categories": categories if categories is not None else ["productivity"],
        "frequency": frequency,
        "source_diversity": source_diversity,
        "representative_voices": (
            representative_voices
            if representative_voices is not None
            else [VOICE_ID_1, VOICE_ID_2, VOICE_ID_3]
        ),
        "confidence": confidence,
    }


def _haiku_payload(patterns: list[dict[str, Any]]) -> str:
    return json.dumps({"patterns": patterns}, ensure_ascii=False)


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
# Migration 009 schema check
# ----------------------------------------------------------------------


def test_migration_009_defines_patterns_table_with_unique_and_indexes() -> None:
    sql_path = REPO_ROOT / "migrations" / "009_patterns.sql"
    sql = sql_path.read_text(encoding="utf-8").lower()

    assert "create table if not exists patterns" in sql
    # Required columns called out in the acceptance criteria.
    for col in (
        "week_iso",
        "pain",
        "categories",
        "frequency",
        "source_diversity",
        "representative_voices",
        "confidence",
    ):
        assert col in sql, f"migration 009 missing column: {col}"
    # representative_voices must be a UUID array.
    assert re.search(r"representative_voices\s+uuid\[\]", sql), (
        "representative_voices must be declared as uuid[]"
    )
    # categories must be a TEXT array.
    assert re.search(r"categories\s+text\[\]", sql), (
        "categories must be declared as text[]"
    )
    # UNIQUE (week_iso, pain) — the upsert hinge.
    assert re.search(
        r"create unique index.*?patterns.*?\(\s*week_iso\s*,\s*pain\s*\)",
        sql,
        flags=re.DOTALL,
    ), "patterns UNIQUE (week_iso, pain) index not found"
    # Required helper index.
    assert "idx_patterns_week" in sql


# ----------------------------------------------------------------------
# week_iso generator
# ----------------------------------------------------------------------


def test_current_week_iso_uses_iso_calendar_yyyy_www_format() -> None:
    from datetime import datetime, timezone

    # Mid-week (Wednesday) so week boundaries don't trip us up.
    fixed = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    iso = fixed.isocalendar()
    assert current_week_iso(fixed) == f"{iso.year:04d}-W{iso.week:02d}"


def test_current_week_iso_zero_pads_single_digit_week() -> None:
    from datetime import datetime, timezone

    fixed = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
    out = current_week_iso(fixed)
    assert re.fullmatch(r"\d{4}-W\d{2}", out), out


def test_current_week_iso_defaults_to_now_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    fixed = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeDT:
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            assert tz is timezone.utc
            return fixed

    monkeypatch.setattr(extractor_mod, "datetime", _FakeDT)
    iso = fixed.isocalendar()
    assert current_week_iso() == f"{iso.year:04d}-W{iso.week:02d}"


# ----------------------------------------------------------------------
# parse_haiku_response
# ----------------------------------------------------------------------


def test_parse_haiku_response_accepts_clean_json() -> None:
    raw = _haiku_payload([_pattern(pain="ペイン A")])

    out = parse_haiku_response(raw, voice_ids=ALL_VOICE_IDS)

    assert len(out) == 1
    assert out[0]["pain"] == "ペイン A"
    assert out[0]["frequency"] == 3
    assert out[0]["source_diversity"] == 2
    assert out[0]["confidence"] == 0.8


def test_parse_haiku_response_strips_code_fence_wrapping() -> None:
    raw = "```json\n" + _haiku_payload([_pattern(pain="x")]) + "\n```"

    out = parse_haiku_response(raw, voice_ids=ALL_VOICE_IDS)

    assert len(out) == 1


def test_parse_haiku_response_drops_unknown_voice_uuids() -> None:
    unknown_uuid = "99999999-9999-9999-9999-999999999999"
    raw = _haiku_payload(
        [_pattern(pain="x", representative_voices=[VOICE_ID_1, unknown_uuid])]
    )

    out = parse_haiku_response(raw, voice_ids=ALL_VOICE_IDS)

    assert out[0]["representative_voices"] == [VOICE_ID_1]


def test_parse_haiku_response_raises_on_non_json_text() -> None:
    with pytest.raises(ValueError):
        parse_haiku_response("not json at all", voice_ids=ALL_VOICE_IDS)


def test_parse_haiku_response_raises_on_missing_patterns_key() -> None:
    with pytest.raises(ValueError):
        parse_haiku_response('{"foo": []}', voice_ids=ALL_VOICE_IDS)


def test_parse_haiku_response_raises_on_invalid_uuid() -> None:
    raw = _haiku_payload(
        [_pattern(pain="x", representative_voices=["not-a-uuid"])]
    )

    with pytest.raises(ValueError):
        parse_haiku_response(raw, voice_ids=ALL_VOICE_IDS)


def test_parse_haiku_response_raises_on_confidence_out_of_range() -> None:
    raw = _haiku_payload([_pattern(pain="x", confidence=1.5)])

    with pytest.raises(ValueError):
        parse_haiku_response(raw, voice_ids=ALL_VOICE_IDS)


def test_parse_haiku_response_accepts_empty_patterns_list() -> None:
    assert parse_haiku_response('{"patterns": []}', voice_ids=ALL_VOICE_IDS) == []


# ----------------------------------------------------------------------
# filter_and_clamp
# ----------------------------------------------------------------------


def test_filter_drops_frequency_below_three() -> None:
    raw = [
        _pattern(pain="below", frequency=2),
        _pattern(pain="ok", frequency=MIN_FREQUENCY),
    ]
    parsed = parse_haiku_response(_haiku_payload(raw), voice_ids=ALL_VOICE_IDS)

    out = filter_and_clamp(parsed)

    assert {p["pain"] for p in out} == {"ok"}


def test_filter_keeps_frequency_at_threshold() -> None:
    parsed = parse_haiku_response(
        _haiku_payload([_pattern(pain="threshold", frequency=MIN_FREQUENCY)]),
        voice_ids=ALL_VOICE_IDS,
    )

    out = filter_and_clamp(parsed)

    assert len(out) == 1


def test_clamp_confidence_when_source_diversity_below_two() -> None:
    parsed = parse_haiku_response(
        _haiku_payload(
            [_pattern(pain="single-source", source_diversity=1, confidence=0.9)]
        ),
        voice_ids=ALL_VOICE_IDS,
    )

    out = filter_and_clamp(parsed)

    assert out[0]["confidence"] == LOW_DIVERSITY_CONFIDENCE_CAP


def test_clamp_does_not_raise_already_low_confidence() -> None:
    parsed = parse_haiku_response(
        _haiku_payload(
            [_pattern(pain="single-source", source_diversity=1, confidence=0.2)]
        ),
        voice_ids=ALL_VOICE_IDS,
    )

    out = filter_and_clamp(parsed)

    assert out[0]["confidence"] == pytest.approx(0.2)


def test_clamp_skipped_when_source_diversity_two_or_more() -> None:
    parsed = parse_haiku_response(
        _haiku_payload(
            [_pattern(pain="diverse", source_diversity=2, confidence=0.95)]
        ),
        voice_ids=ALL_VOICE_IDS,
    )

    out = filter_and_clamp(parsed)

    assert out[0]["confidence"] == pytest.approx(0.95)


# ----------------------------------------------------------------------
# Upsert SQL contract
# ----------------------------------------------------------------------


def test_upsert_sql_uses_on_conflict_week_iso_pain_do_update() -> None:
    normalized = " ".join(UPSERT_PATTERN_SQL.split()).lower()
    assert "insert into patterns" in normalized
    assert "on conflict (week_iso, pain) do update" in normalized
    # The columns that must be refreshed on conflict.
    for col in (
        "categories",
        "frequency",
        "source_diversity",
        "representative_voices",
        "confidence",
        "updated_at",
    ):
        assert col in normalized, f"upsert refresh missing column: {col}"


def test_upsert_inserts_once_then_updates_on_second_run() -> None:
    conn = _FakeConn()
    patterns = [
        {
            "pain": "重複の SaaS 課金がしんどい",
            "categories": ["finance"],
            "frequency": 4,
            "source_diversity": 2,
            "representative_voices": [VOICE_ID_1, VOICE_ID_2],
            "confidence": 0.7,
        }
    ]

    first = upsert_patterns(
        conn,  # type: ignore[arg-type]
        patterns,
        week_iso="2026-W21",
        raw_response_snippet="raw1",
    )
    # Second call: same key, refreshed numbers.
    refreshed = [
        {
            "pain": "重複の SaaS 課金がしんどい",
            "categories": ["finance", "subscription"],
            "frequency": 7,
            "source_diversity": 3,
            "representative_voices": [VOICE_ID_1, VOICE_ID_2, VOICE_ID_3],
            "confidence": 0.85,
        }
    ]
    second = upsert_patterns(
        conn,  # type: ignore[arg-type]
        refreshed,
        week_iso="2026-W21",
        raw_response_snippet="raw2",
    )

    assert first == 1
    assert second == 1
    # Only one row total — fake DB enforces UNIQUE (week_iso, pain).
    assert len(conn.patterns_by_key) == 1
    final = conn.patterns_by_key[("2026-W21", "重複の SaaS 課金がしんどい")]
    assert final["frequency"] == 7
    assert final["source_diversity"] == 3
    assert final["confidence"] == 0.85
    assert final["categories"] == ["finance", "subscription"]
    assert conn.insert_count == 1
    assert conn.update_count == 1


# ----------------------------------------------------------------------
# run_once — soft-fail paths
# ----------------------------------------------------------------------


def test_run_once_returns_zero_when_voices_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(voices_rows=[])
    client = _FakeAnthropic(text="(should not be called)")

    upserted = run_once(conn, client, week_iso="2026-W21")  # type: ignore[arg-type]

    assert upserted == 0
    # Haiku must not be called when there are no voices.
    assert client.calls == []
    assert conn.patterns_by_key == {}


def _voice_row(
    voice_id: str = VOICE_ID_1,
    *,
    source: str = "apple_rss",
    rating: int = 2,
) -> tuple[Any, ...]:
    from datetime import datetime, timezone

    posted_at = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
    return (
        voice_id,
        source,
        posted_at,
        f"title-{voice_id[:4]}",
        f"body-{voice_id[:4]}",
        {"rating": rating, "country": "jp", "lang": "ja"},
    )


def test_run_once_exits_zero_on_malformed_haiku_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(voices_rows=[_voice_row()])
    client = _FakeAnthropic(text="this is not JSON at all")

    sentry_calls: list[tuple[str, dict[str, Any]]] = []

    def fake_capture_message(msg: str, **kwargs: Any) -> None:
        sentry_calls.append((msg, kwargs))

    monkeypatch.setattr(
        extractor_mod.sentry_sdk, "capture_message", fake_capture_message
    )

    upserted = run_once(conn, client, week_iso="2026-W21")  # type: ignore[arg-type]

    assert upserted == 0
    assert conn.patterns_by_key == {}
    assert len(sentry_calls) == 1
    msg, kwargs = sentry_calls[0]
    assert "malformed" in msg.lower()
    assert kwargs.get("level") == "warning"


def test_run_once_exits_zero_when_only_apple_source_present() -> None:
    """Apple のみ (source_diversity=1) でも raise せず exit 0。"""
    conn = _FakeConn(
        voices_rows=[
            _voice_row(VOICE_ID_1, source="apple_rss"),
            _voice_row(VOICE_ID_2, source="apple_rss"),
            _voice_row(VOICE_ID_3, source="apple_rss"),
        ]
    )
    # Haiku returns a single pattern with source_diversity=1.
    payload = _haiku_payload(
        [_pattern(pain="apple-only", source_diversity=1, confidence=0.9)]
    )
    client = _FakeAnthropic(text=payload)

    upserted = run_once(conn, client, week_iso="2026-W21")  # type: ignore[arg-type]

    # Pattern survived frequency >= 3 filter, confidence was clamped.
    assert upserted == 1
    row = conn.patterns_by_key[("2026-W21", "apple-only")]
    assert row["confidence"] == LOW_DIVERSITY_CONFIDENCE_CAP


def test_run_once_drops_low_frequency_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn(
        voices_rows=[
            _voice_row(VOICE_ID_1),
            _voice_row(VOICE_ID_2),
            _voice_row(VOICE_ID_3),
        ]
    )
    payload = _haiku_payload(
        [
            _pattern(pain="below", frequency=2),
            _pattern(pain="ok", frequency=3),
        ]
    )
    client = _FakeAnthropic(text=payload)

    upserted = run_once(conn, client, week_iso="2026-W21")  # type: ignore[arg-type]

    assert upserted == 1
    assert set(conn.patterns_by_key.keys()) == {("2026-W21", "ok")}


def test_run_once_passes_system_prompt_to_haiku() -> None:
    conn = _FakeConn(voices_rows=[_voice_row()])
    payload = _haiku_payload([_pattern(pain="x")])
    client = _FakeAnthropic(text=payload)

    run_once(conn, client, week_iso="2026-W21")  # type: ignore[arg-type]

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == CLAUDE_MODEL
    assert call["system"] == SYSTEM_PROMPT


# ----------------------------------------------------------------------
# Workflow YAML cron schedule
# ----------------------------------------------------------------------


def test_workflow_cron_runs_tue_thu_sat_at_03_utc() -> None:
    import yaml as _yaml

    wf_path = REPO_ROOT / ".github" / "workflows" / "idea-mining-extractor.yml"
    # PyYAML treats bare `on` as Python True — feed via safe_load and accept either key.
    parsed = _yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    triggers = parsed.get("on") if "on" in parsed else parsed.get(True)
    assert isinstance(triggers, dict), f"workflow 'on' block missing: {parsed!r}"
    schedules = triggers["schedule"]
    crons = [item["cron"] for item in schedules]
    assert "0 3 * * 2,4,6" in crons
    assert "workflow_dispatch" in triggers


def test_workflow_passes_anthropic_api_key_env() -> None:
    wf_path = REPO_ROOT / ".github" / "workflows" / "idea-mining-extractor.yml"
    text = wf_path.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}" in text


# ----------------------------------------------------------------------
# SYSTEM_PROMPT snapshot
# ----------------------------------------------------------------------


SYSTEM_PROMPT_SNAPSHOT: str = """あなたは Hibi のアイデアマイニング担当のアナリストです。

与えられる入力は、過去 7 日に集めた個人開発者向けプロダクトに対する ★1-4 のユーザーレビュー (`voices`) のリストです。
各 voice には id (UUID)、source (e.g. 'apple_rss')、posted_at、title、body、rating が含まれます。

あなたのタスクは、これらの voice を「構造的なペイン (pain)」単位でクラスタリングし、JSON のみで返すことです。

クラスタリングの方針:
- pain は「あるプロダクト名固有の不満」ではなく、「個人開発者が複数のプロダクトで繰り返し直面しうる構造」として抽出する。
- 同じ構造のペインは違うプロダクト・違う表現でも 1 つの pain にまとめる。
- 表面的なバグ報告 (e.g. 「クラッシュした」「起動しない」) は構造的ペインではないため除外する。
- 機能要望そのもの (e.g. 「ダークモードが欲しい」) は構造的ペインではないため除外する。

出力スキーマ (JSON のみ。前後に余計な文字・コードブロックを入れない):
{
  "patterns": [
    {
      "pain": "短く具体的な日本語ラベル。プロダクト名は入れない。",
      "categories": ["topical-tag-1", "topical-tag-2"],
      "frequency": 5,
      "source_diversity": 2,
      "representative_voices": ["<voice-uuid-1>", "<voice-uuid-2>", "<voice-uuid-3>"],
      "confidence": 0.8
    }
  ]
}

各フィールドの意味:
- pain: その構造的ペインの短文ラベル (日本語)。固有名詞を入れない。
- categories: pain を分類する topical タグの配列。0 件可。
- frequency: その pain にまとめた voice の総数 (整数)。
- source_diversity: その pain にまとめた voice の distinct な source 数 (整数)。
- representative_voices: その pain を代表する voice の id (UUID) の配列。最大 5 件まで。入力に存在する id のみ使う。
- confidence: 0.0-1.0 の浮動小数。クラスタの確からしさ。

ルール:
- frequency が 3 未満になる pain は patterns に含めない (出力から除外する)。
- source_diversity が 2 未満 (= 1 source のみ) の pain は confidence を 0.5 以下に抑える。
- 入力 voice が 0 件、あるいは抽出に値する構造的ペインが無い場合は {"patterns": []} を返す。
- representative_voices の UUID は入力に実在するものから選ぶ。新たに生成しない。
- JSON 以外の文字 (前置き、後置き、コードフェンス) を絶対に出力しない。
"""


def test_system_prompt_snapshot() -> None:
    """SYSTEM_PROMPT contract is intentionally locked verbatim.

    Update SYSTEM_PROMPT_SNAPSHOT only when the team has decided to
    change the Haiku contract for the extractor.
    """
    assert SYSTEM_PROMPT == SYSTEM_PROMPT_SNAPSHOT
