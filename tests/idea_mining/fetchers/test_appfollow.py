"""Tests for `idea_mining.fetchers.appfollow`.

AppFollow Free fetcher の挙動 (★5 除外 / defensive parsing / dedupe key /
retry & Sentry alert / sources.yaml パース / URL 組み立て / migration 008
互換) を最小限のスコープで検証する。

外部 HTTP / DB / Sentry は dependency-inject や monkeypatch で全部モック
する。実 Neon / 実 AppFollow API は叩かない。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from idea_mining.fetchers import appfollow
from idea_mining.fetchers.appfollow import (
    APPFOLLOW_API_BASE,
    FETCH_WINDOW_DAYS,
    INSERT_SQL,
    LANG_BY_COUNTRY,
    RETRY_DELAYS_SECONDS,
    SOURCE_NAME,
    AppFollowApp,
    _build_url,
    fetch_one,
    insert_voices,
    load_appfollow_apps,
    parse_review_entries,
    run_once,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _review(
    rating: int,
    review_id: str,
    *,
    content: str | None = None,
    title: str | None = None,
    dt: str = "2026-05-19T12:34:56+00:00",
    author: str = "anon",
    app_version: str = "1.2.3",
    locale: str = "ja",
    appfollow_id: str | None = None,
    **overrides: Any,
) -> dict:
    body: dict[str, Any] = {
        "review_id": review_id,
        "id": appfollow_id or f"af-{review_id}",
        "rating": rating,
        "content": content if content is not None else f"body-{review_id}",
        "title": title if title is not None else f"title-{review_id}",
        "author": author,
        "user_id": f"user-{review_id}",
        "app_version": app_version,
        "locale": locale,
        "dt": dt,
    }
    body.update(overrides)
    return body


def _wrap(*reviews: dict, shape: str = "reviews.list") -> dict:
    """top-level の構造バリエーションを試す helper."""
    items = list(reviews)
    if shape == "reviews.list":
        return {"reviews": {"list": items}}
    if shape == "reviews":
        return {"reviews": items}
    if shape == "data.list":
        return {"data": {"list": items}}
    if shape == "data":
        return {"data": items}
    if shape == "items":
        return {"items": items}
    raise ValueError(f"unknown shape: {shape}")


# ----------------------------------------------------------------------
# Parser tests
# ----------------------------------------------------------------------


def test_parse_drops_rating_5_and_keeps_1_through_4() -> None:
    payload = _wrap(
        _review(1, "r1"),
        _review(2, "r2"),
        _review(3, "r3"),
        _review(4, "r4"),
        _review(5, "r5"),  # excluded
    )

    rows = parse_review_entries(
        payload, country="jp", app_id="1232780281", app_name="Notion"
    )

    ratings = sorted(r["meta"]["rating"] for r in rows)
    assert ratings == [1, 2, 3, 4]
    assert all(r["source"] == SOURCE_NAME for r in rows)
    assert "r5" not in {r["source_id"] for r in rows}


def test_parse_skips_invalid_rating() -> None:
    payload = _wrap(
        _review(0, "r0"),  # rating out of range
        _review(6, "r6"),  # rating out of range
        {"review_id": "no_rating", "content": "x", "dt": "2026-05-19T00:00:00+00:00"},
        _review(2, "r2"),  # kept
    )

    rows = parse_review_entries(payload, country="jp", app_id="1", app_name="X")

    assert [r["source_id"] for r in rows] == ["r2"]


def test_parse_skips_missing_posted_at() -> None:
    payload = _wrap(
        {"review_id": "no_dt", "rating": 2, "content": "x"},
        _review(3, "ok"),
    )

    rows = parse_review_entries(payload, country="jp", app_id="1", app_name="X")

    assert [r["source_id"] for r in rows] == ["ok"]


def test_parse_falls_back_to_internal_id_when_review_id_missing() -> None:
    payload = _wrap(
        {
            "id": "af-only-1",
            "rating": 3,
            "content": "x",
            "dt": "2026-05-19T00:00:00+00:00",
        },
    )

    rows = parse_review_entries(payload, country="jp", app_id="1", app_name="X")

    assert rows[0]["source_id"] == "af-only-1"


def test_parse_meta_shape() -> None:
    payload = _wrap(_review(3, "r1", appfollow_id="af-r1", locale="ja"))

    rows = parse_review_entries(
        payload, country="jp", app_id="1232780281", app_name="Notion"
    )

    meta = rows[0]["meta"]
    assert meta["rating"] == 3
    assert meta["author"] == "anon"
    assert meta["country"] == "jp"
    assert meta["lang"] == "ja"
    assert meta["app_version"] == "1.2.3"
    assert meta["app_id"] == "1232780281"
    assert meta["app_name"] == "Notion"
    assert meta["appfollow_id"] == "af-r1"


def test_parse_locale_falls_back_to_country_lang_when_missing() -> None:
    payload = _wrap(_review(2, "r1", locale=""))

    rows = parse_review_entries(payload, country="jp", app_id="1", app_name="X")

    assert rows[0]["meta"]["lang"] == LANG_BY_COUNTRY["jp"]


@pytest.mark.parametrize(
    "shape", ["reviews.list", "reviews", "data.list", "data", "items"]
)
def test_parse_handles_multiple_top_level_shapes(shape: str) -> None:
    payload = _wrap(_review(2, "r1"), _review(4, "r2"), shape=shape)

    rows = parse_review_entries(payload, country="jp", app_id="1", app_name="X")

    assert sorted(r["source_id"] for r in rows) == ["r1", "r2"]


def test_parse_returns_empty_when_no_reviews() -> None:
    assert parse_review_entries(
        {"reviews": {"list": []}}, country="jp", app_id="1", app_name="X"
    ) == []
    assert parse_review_entries({}, country="jp", app_id="1", app_name="X") == []
    assert parse_review_entries(
        {"reviews": {}}, country="jp", app_id="1", app_name="X"
    ) == []


def test_parse_uses_content_field_for_body() -> None:
    payload = _wrap(_review(3, "r1", content="hello world"))

    rows = parse_review_entries(payload, country="jp", app_id="1", app_name="X")

    assert rows[0]["body"] == "hello world"


# ----------------------------------------------------------------------
# URL build tests
# ----------------------------------------------------------------------


def test_build_url_includes_required_query_params() -> None:
    url = _build_url("1232780281", "jp", days=7)

    assert url.startswith(APPFOLLOW_API_BASE)
    assert "ext_id=1232780281" in url
    assert "country=jp" in url
    assert "page=1" in url
    assert "from=" in url
    assert "to=" in url


def test_build_url_date_window_uses_today_and_seven_days_ago() -> None:
    url = _build_url("1", "jp", days=FETCH_WINDOW_DAYS)
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=FETCH_WINDOW_DAYS)

    assert f"to={today.isoformat()}" in url
    assert f"from={since.isoformat()}" in url


# ----------------------------------------------------------------------
# fetch_one retry tests
# ----------------------------------------------------------------------


def test_fetch_one_returns_payload_on_first_try() -> None:
    calls: list[str] = []

    def http_get(url: str, headers: dict[str, str]) -> dict:
        calls.append(url)
        assert headers["X-AppFollow-API-Token"] == "tok"
        return {"reviews": {"list": []}}

    out = fetch_one(
        "jp", "1", api_token="tok", http_get=http_get, sleep_fn=lambda _s: None
    )

    assert out == {"reviews": {"list": []}}
    assert len(calls) == 1


def test_fetch_one_retries_until_success() -> None:
    attempts = {"n": 0}

    def http_get(url: str, headers: dict[str, str]) -> dict:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("flaky")
        return {"reviews": {"list": []}}

    out = fetch_one(
        "jp", "1", api_token="tok", http_get=http_get, sleep_fn=lambda _s: None
    )

    assert out == {"reviews": {"list": []}}
    assert attempts["n"] == 3


def test_fetch_one_returns_none_after_all_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    def fake_capture(msg: str, *, level: str = "info") -> None:
        sent.append((msg, {"level": level}))

    monkeypatch.setattr(appfollow.sentry_sdk, "capture_message", fake_capture)

    def http_get(url: str, headers: dict[str, str]) -> dict:
        raise TimeoutError("always")

    out = fetch_one(
        "jp", "1", api_token="tok", http_get=http_get, sleep_fn=lambda _s: None
    )

    assert out is None
    # 1 + len(RETRY_DELAYS_SECONDS) attempts = 6
    assert len(sent) == 1
    assert sent[0][1]["level"] == "error"
    assert "5 consecutive retries exhausted" in sent[0][0]
    # sanity: retry delays = 5 entries
    assert len(RETRY_DELAYS_SECONDS) == 5


# ----------------------------------------------------------------------
# insert_voices tests
# ----------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.rowcount = 1

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str, params: dict) -> None:
        self.executed.append((sql, params))


class _FakeConn:
    def __init__(self) -> None:
        self._cur = _FakeCursor()
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return self._cur

    def commit(self) -> None:
        self.commits += 1


def test_insert_voices_returns_zero_for_empty_rows() -> None:
    conn = _FakeConn()

    assert insert_voices(conn, []) == 0  # type: ignore[arg-type]
    assert conn.commits == 0


def test_insert_voices_uses_expected_sql_and_columns() -> None:
    conn = _FakeConn()
    rows = [
        {
            "source": SOURCE_NAME,
            "source_id": "r1",
            "posted_at": "2026-05-19T00:00:00+00:00",
            "title": "t",
            "body": "b",
            "meta": {"rating": 3},
        }
    ]

    inserted = insert_voices(conn, rows)  # type: ignore[arg-type]

    assert inserted == 1
    assert conn.commits == 1
    sql, params = conn._cur.executed[0]
    assert "INSERT INTO voices" in sql
    assert "ON CONFLICT (source, source_id) DO NOTHING" in sql
    assert params["source"] == SOURCE_NAME
    assert params["source_id"] == "r1"


# ----------------------------------------------------------------------
# sources.yaml loader tests
# ----------------------------------------------------------------------


def test_load_appfollow_apps_filters_disabled(tmp_path: Path) -> None:
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "appfollow_apps": [
                    {
                        "name": "Notion",
                        "app_id": "1232780281",
                        "country": ["jp"],
                        "enabled": True,
                    },
                    {
                        "name": "Disabled",
                        "app_id": "999",
                        "country": ["jp"],
                        "enabled": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    apps = load_appfollow_apps(yaml_path)

    assert [a.name for a in apps] == ["Notion"]
    assert apps[0].app_id == "1232780281"
    assert apps[0].countries == ("jp",)


def test_load_appfollow_apps_skips_entries_without_countries(tmp_path: Path) -> None:
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "appfollow_apps": [
                    {"name": "NoCountry", "app_id": "1", "country": [], "enabled": True},
                    {
                        "name": "Notion",
                        "app_id": "2",
                        "country": ["jp"],
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    apps = load_appfollow_apps(yaml_path)

    assert [a.name for a in apps] == ["Notion"]


def test_load_appfollow_apps_ignores_apple_apps_section(tmp_path: Path) -> None:
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "apple_apps": [
                    {"name": "Old", "app_id": "1", "country": ["jp"], "enabled": True},
                ],
                "appfollow_apps": [
                    {
                        "name": "New",
                        "app_id": "2",
                        "country": ["jp"],
                        "enabled": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    apps = load_appfollow_apps(yaml_path)

    assert [a.name for a in apps] == ["New"]


def test_repo_sources_yaml_has_at_most_two_enabled_appfollow_apps() -> None:
    """Free プランの 2 apps cap を YAML レベルで保証する。"""
    repo_yaml = REPO_ROOT / "sources.yaml"
    apps = load_appfollow_apps(repo_yaml)

    assert len(apps) <= 2, (
        f"AppFollow Free is capped at 2 apps; got {len(apps)} enabled. "
        f"Disable some entries in sources.yaml or upgrade the plan."
    )


# ----------------------------------------------------------------------
# run_once orchestration tests
# ----------------------------------------------------------------------


def test_run_once_aggregates_stats_across_apps() -> None:
    conn = _FakeConn()

    def http_get(url: str, headers: dict[str, str]) -> dict:
        # ext_id ごとに違うレビューを返す
        if "ext_id=1" in url:
            return _wrap(_review(2, "r1"), _review(5, "r5"))
        return _wrap(_review(3, "r2"))

    apps = [
        AppFollowApp(name="A", app_id="1", countries=("jp",)),
        AppFollowApp(name="B", app_id="2", countries=("jp",)),
    ]

    stats = run_once(
        apps,
        conn=conn,  # type: ignore[arg-type]
        api_token="tok",
        http_get=http_get,
        sleep_fn=lambda _s: None,
    )

    # A: r1 only (r5 excluded), B: r2 → parsed=2 inserted=2
    assert stats.apps_total == 2
    assert stats.pairs_total == 2
    assert stats.pairs_skipped == 0
    assert stats.rows_parsed == 2
    assert stats.rows_inserted == 2
    assert stats.failures == []


def test_run_once_skips_failed_app_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(appfollow.sentry_sdk, "capture_message", lambda *a, **k: None)
    conn = _FakeConn()

    def http_get(url: str, headers: dict[str, str]) -> dict:
        if "ext_id=fail" in url:
            raise TimeoutError("always")
        return _wrap(_review(3, "ok"))

    apps = [
        AppFollowApp(name="Fail", app_id="fail", countries=("jp",)),
        AppFollowApp(name="OK", app_id="ok", countries=("jp",)),
    ]

    stats = run_once(
        apps,
        conn=conn,  # type: ignore[arg-type]
        api_token="tok",
        http_get=http_get,
        sleep_fn=lambda _s: None,
    )

    assert stats.pairs_skipped == 1
    assert "jp/fail" in stats.failures
    assert stats.rows_inserted == 1


# ----------------------------------------------------------------------
# Migration 008 sanity (INSERT_SQL targets the voices table contract)
# ----------------------------------------------------------------------


def test_insert_sql_matches_migration_008_contract() -> None:
    # migration 008 が voices(source, source_id) UNIQUE を前提にしているので、
    # INSERT 側もそのキーで ON CONFLICT を取っていることをここで pin する。
    assert "INSERT INTO voices" in INSERT_SQL
    assert "ON CONFLICT (source, source_id) DO NOTHING" in INSERT_SQL
    for column in ("source", "source_id", "posted_at", "title", "body", "meta"):
        assert f"%({column})s" in INSERT_SQL
