"""Tests for `idea_mining.fetchers.apple_rss`.

Apple iTunes RSS fetcher の挙動 (★5 除外 / meta JSONB / ON CONFLICT NoOp /
retry & Sentry alert / sources.yaml パース / migration 008) を最小限の
スコープで検証する。

外部 HTTP / DB / Sentry は dependency-inject や monkeypatch で全部モック
する。実 Neon / 実 Apple API は叩かない。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from idea_mining.fetchers import apple_rss
from idea_mining.fetchers.apple_rss import (
    APPLE_RSS_URL_FMT,
    INSERT_SQL,
    LANG_BY_COUNTRY,
    RETRY_DELAYS_SECONDS,
    SOURCE_NAME,
    AppleApp,
    fetch_one,
    insert_voices,
    load_apple_apps,
    parse_review_entries,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _entry(rating: str, review_id: str, **overrides: Any) -> dict:
    base = {
        "id": {"label": review_id},
        "title": {"label": f"title-{review_id}"},
        "content": {"label": f"body-{review_id}"},
        "im:rating": {"label": rating},
        "im:version": {"label": "1.2.3"},
        "author": {"name": {"label": f"user-{review_id}"}},
        "updated": {"label": "2026-05-19T12:34:56-07:00"},
    }
    base.update(overrides)
    return base


def _payload(*entries: dict) -> dict:
    return {"feed": {"entry": list(entries)}}


# ----------------------------------------------------------------------
# Parser tests
# ----------------------------------------------------------------------


def test_parse_drops_rating_5_and_keeps_1_through_4() -> None:
    payload = _payload(
        _entry("1", "r1"),
        _entry("2", "r2"),
        _entry("3", "r3"),
        _entry("4", "r4"),
        _entry("5", "r5"),  # excluded
    )

    rows = parse_review_entries(payload, country="jp", app_id="1232780281")

    ratings = sorted(r["meta"]["rating"] for r in rows)
    assert ratings == [1, 2, 3, 4]
    assert all(r["source"] == SOURCE_NAME for r in rows)
    assert "r5" not in {r["source_id"] for r in rows}


def test_parse_meta_has_required_fields() -> None:
    payload = _payload(_entry("2", "r1"))

    [row] = parse_review_entries(payload, country="jp", app_id="1232780281")

    meta = row["meta"]
    for key in ("version", "author", "country", "lang", "rating"):
        assert key in meta, f"meta missing required key: {key}"
    assert meta["version"] == "1.2.3"
    assert meta["author"] == "user-r1"
    assert meta["country"] == "jp"
    assert meta["lang"] == "ja"
    assert meta["rating"] == 2


def test_parse_country_jp_yields_meta_lang_ja() -> None:
    payload = _payload(_entry("3", "r1"))

    [row] = parse_review_entries(payload, country="jp", app_id="1")

    assert row["meta"]["country"] == "jp"
    assert row["meta"]["lang"] == "ja"


def test_parse_country_us_yields_meta_lang_en() -> None:
    # `LANG_BY_COUNTRY` で us → en にマップされていることの sanity check.
    # 運用上は jp のみだが、lookup ロジックの境界として確認。
    payload = _payload(_entry("3", "r1"))

    [row] = parse_review_entries(payload, country="us", app_id="1")

    assert row["meta"]["lang"] == "en"


def test_parse_handles_single_entry_dict() -> None:
    # Apple feed は entries が 1 件のとき list ではなく dict になるケースがある。
    payload = {"feed": {"entry": _entry("2", "r1")}}

    rows = parse_review_entries(payload, country="jp", app_id="1")

    assert len(rows) == 1
    assert rows[0]["source_id"] == "r1"


def test_parse_handles_missing_entry_field() -> None:
    # feed.entry が無い場合 (= レビューゼロ) は空リスト。
    assert parse_review_entries({"feed": {}}, country="jp", app_id="1") == []


def test_parse_skips_entry_without_rating() -> None:
    # `im:rating` を欠くエントリは app metadata 等として skip する。
    payload = _payload({"id": {"label": "metadata"}}, _entry("4", "r1"))

    rows = parse_review_entries(payload, country="jp", app_id="1")

    assert len(rows) == 1
    assert rows[0]["source_id"] == "r1"


def test_parse_review_body_and_title_preserved() -> None:
    payload = _payload(_entry("1", "r99"))

    [row] = parse_review_entries(payload, country="jp", app_id="1")

    assert row["title"] == "title-r99"
    assert row["body"] == "body-r99"
    assert row["posted_at"] == "2026-05-19T12:34:56-07:00"


# ----------------------------------------------------------------------
# Retry / backoff / Sentry alert
# ----------------------------------------------------------------------


def test_fetch_one_succeeds_on_first_try() -> None:
    payload = _payload(_entry("2", "r1"))
    calls: list[str] = []

    def http_get(url: str) -> dict:
        calls.append(url)
        return payload

    sleeps: list[float] = []

    result = fetch_one(
        "jp", "1", http_get=http_get, sleep_fn=lambda s: sleeps.append(s)
    )

    assert result is payload
    assert len(calls) == 1
    assert sleeps == []
    assert calls[0] == APPLE_RSS_URL_FMT.format(country="jp", app_id="1")


def test_fetch_one_retries_with_exp_backoff_then_sentry_on_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """初期1 + 5 retries が全部失敗したら Sentry alert を発火し None を返す。"""
    calls: list[str] = []

    def always_fail(url: str) -> dict:
        calls.append(url)
        raise TimeoutError("simulated")

    sleeps: list[float] = []
    sentry_calls: list[tuple[str, dict]] = []

    def fake_capture_message(msg: str, **kwargs: Any) -> None:
        sentry_calls.append((msg, kwargs))

    monkeypatch.setattr(
        apple_rss.sentry_sdk, "capture_message", fake_capture_message
    )

    result = fetch_one(
        "jp",
        "999",
        http_get=always_fail,
        sleep_fn=lambda s: sleeps.append(s),
    )

    assert result is None
    # 1 initial + 5 retries
    assert len(calls) == 1 + len(RETRY_DELAYS_SECONDS)
    # Sleeps happen between each retry — 5 total, matching the constant.
    assert sleeps == list(RETRY_DELAYS_SECONDS)
    # Exactly one Sentry alert with level=error and app coords in the body.
    assert len(sentry_calls) == 1
    msg, kwargs = sentry_calls[0]
    assert "jp/999" in msg
    assert kwargs.get("level") == "error"


def test_fetch_one_recovers_mid_retry() -> None:
    """途中で復旧したら Sentry alert は発火せず正常 payload を返す。"""
    payload = _payload(_entry("3", "r1"))
    attempt_counter = {"n": 0}

    def flaky(url: str) -> dict:
        attempt_counter["n"] += 1
        if attempt_counter["n"] < 3:
            raise TimeoutError("flaky")
        return payload

    sleeps: list[float] = []

    result = fetch_one(
        "jp", "1", http_get=flaky, sleep_fn=lambda s: sleeps.append(s)
    )

    assert result is payload
    # 1 initial + 2 retries = succeed on 3rd attempt
    assert attempt_counter["n"] == 3
    # Sleeps happened only between failed attempts.
    assert sleeps == [1, 2]


# ----------------------------------------------------------------------
# INSERT SQL contract — ON CONFLICT DO NOTHING
# ----------------------------------------------------------------------


def test_insert_sql_uses_on_conflict_source_source_id_do_nothing() -> None:
    """同一 (source, source_id) の再 insert が NoOp になることを SQL レベルで保証。"""
    normalized = re.sub(r"\s+", " ", INSERT_SQL).strip().lower()
    assert "insert into voices" in normalized
    assert "on conflict (source, source_id) do nothing" in normalized


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.rowcount = 1

    def execute(self, sql: str, params: dict) -> None:
        self.executed.append((sql, params))

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1


def test_insert_voices_passes_meta_as_jsonb_and_uses_conflict_sql() -> None:
    conn = _FakeConn()
    rows = [
        {
            "source": SOURCE_NAME,
            "source_id": "r1",
            "posted_at": "2026-05-19T12:34:56-07:00",
            "title": "t",
            "body": "b",
            "meta": {
                "version": "1.0",
                "author": "u",
                "country": "jp",
                "lang": "ja",
                "rating": 3,
            },
        },
    ]

    inserted = insert_voices(conn, rows)  # type: ignore[arg-type]

    assert inserted == 1
    assert conn.commits == 1
    assert len(conn.cur.executed) == 1
    sql, params = conn.cur.executed[0]
    normalized = re.sub(r"\s+", " ", sql).strip().lower()
    assert "on conflict (source, source_id) do nothing" in normalized
    # meta must be wrapped for psycopg JSONB serialization.
    from psycopg.types.json import Jsonb

    assert isinstance(params["meta"], Jsonb)


def test_insert_voices_treats_rowcount_zero_as_noop() -> None:
    """ON CONFLICT skip 時は cur.rowcount=0 → inserted カウントを増やさない."""
    conn = _FakeConn()
    conn.cur.rowcount = 0
    rows = [
        {
            "source": SOURCE_NAME,
            "source_id": "dup",
            "posted_at": "2026-05-19T12:34:56-07:00",
            "title": None,
            "body": None,
            "meta": {"rating": 1, "country": "jp", "lang": "ja"},
        }
    ]

    inserted = insert_voices(conn, rows)  # type: ignore[arg-type]

    assert inserted == 0


# ----------------------------------------------------------------------
# sources.yaml apple_apps parsing
# ----------------------------------------------------------------------


def test_load_apple_apps_reads_real_sources_yaml() -> None:
    # 2026-05-21 以降、Apple iTunes Customer Reviews RSS 死亡を受けて
    # sources.yaml の apple_apps セクションは全 entry を enabled: false に
    # 変更し、idea-mining-weekly workflow からも切り離した
    # (Issue #150, ADR: 10_projects/idea-mining/decisions/
    # 2026-05-21-appfollow-free-personal-use.md)。
    # load_apple_apps は enabled=true のみ返すため、本番 sources.yaml に
    # 対しては 0 件で返ることが正しい挙動。fetcher コード自体は将来 Apple
    # が RSS を復活させたときの参照実装として残置している。
    apps = load_apple_apps(REPO_ROOT / "sources.yaml")

    assert apps == [], (
        "apple_apps must be fully disabled in sources.yaml after the "
        "2026-05-21 pivot to AppFollow. Re-enable only if Apple revives "
        "the Customer Reviews RSS endpoint and the ADR is reopened."
    )


def test_load_apple_apps_skips_disabled(tmp_path: Path) -> None:
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "sources": [],
                "apple_apps": [
                    {
                        "name": "Notion",
                        "app_id": "1",
                        "country": ["jp"],
                        "enabled": True,
                    },
                    {
                        "name": "Disabled",
                        "app_id": "2",
                        "country": ["jp"],
                        "enabled": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    apps = load_apple_apps(yaml_path)

    assert [a.name for a in apps] == ["Notion"]


def test_load_apple_apps_does_not_require_apple_apps_key(tmp_path: Path) -> None:
    # 既存 sources.yaml (apple_apps セクション無し) でも壊れない。
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(yaml.safe_dump({"sources": []}), encoding="utf-8")

    assert load_apple_apps(yaml_path) == []


def test_load_apple_apps_skips_entries_with_empty_country(tmp_path: Path) -> None:
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "apple_apps": [
                    {"name": "NoCountry", "app_id": "1", "country": [], "enabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_apple_apps(yaml_path) == []


# ----------------------------------------------------------------------
# Migration 008 schema check (text-level)
# ----------------------------------------------------------------------


def test_migration_008_defines_voices_table_with_unique_and_index() -> None:
    sql_path = REPO_ROOT / "migrations" / "008_voices.sql"
    sql = sql_path.read_text(encoding="utf-8").lower()

    # Table itself.
    assert "create table if not exists voices" in sql
    # Required columns referenced in the fetcher's INSERT.
    for col in ("source", "source_id", "posted_at", "meta"):
        assert col in sql

    # UNIQUE (source, source_id) — required for ON CONFLICT idempotency.
    assert re.search(
        r"create unique index.*?voices.*?\(\s*source\s*,\s*source_id\s*\)",
        sql,
        flags=re.DOTALL,
    ), "voices_source_source_id_uidx not found"

    # idx_voices_source_posted — explicitly named in the acceptance criteria.
    assert "idx_voices_source_posted" in sql


# ----------------------------------------------------------------------
# Module-level constants sanity
# ----------------------------------------------------------------------


def test_retry_delays_constant_matches_spec() -> None:
    assert RETRY_DELAYS_SECONDS == (1, 2, 4, 8, 16)


def test_lang_lookup_jp_is_ja() -> None:
    assert LANG_BY_COUNTRY["jp"] == "ja"


def test_apple_app_dataclass_is_frozen() -> None:
    app = AppleApp(name="x", app_id="1", countries=("jp",))
    with pytest.raises(Exception):
        app.app_id = "2"  # type: ignore[misc]
