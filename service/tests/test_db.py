"""Unit tests for app.db.

These tests monkeypatch the module-level connection pool so they exercise the
exception-handling branches in get_article() without standing up real Postgres.
"""

from __future__ import annotations

import logging

import psycopg
import pytest

from app import db as db_module

ARTICLE_ID = "11111111-1111-1111-1111-111111111111"


class _PoolRaising:
    """Stand-in ConnectionPool whose .connection() raises a given exception."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def connection(self) -> object:
        raise self._exc


def test_get_article_returns_none_on_operational_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pool/connection failures (Neon cold start) must be swallowed → None."""
    fake_pool = _PoolRaising(psycopg.OperationalError("connection closed"))
    monkeypatch.setattr(db_module, "_pool", fake_pool)

    with caplog.at_level(logging.ERROR, logger="app.db"):
        result = db_module.get_article(ARTICLE_ID)

    assert result is None
    # Non-DataError branches must be logged so we can see cold-start churn.
    assert any(
        "get_article: db error" in record.message and ARTICLE_ID in record.message
        for record in caplog.records
    )


def test_get_article_returns_none_on_interface_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """InterfaceError (pool closed / broken) must also be swallowed → None."""
    fake_pool = _PoolRaising(psycopg.InterfaceError("pool is closed"))
    monkeypatch.setattr(db_module, "_pool", fake_pool)

    assert db_module.get_article(ARTICLE_ID) is None


def test_get_article_returns_none_on_data_error_without_logging(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed UUID stays on the silent DataError branch (no error log)."""
    fake_pool = _PoolRaising(psycopg.DataError("invalid input syntax for uuid"))
    monkeypatch.setattr(db_module, "_pool", fake_pool)

    with caplog.at_level(logging.ERROR, logger="app.db"):
        result = db_module.get_article("not-a-uuid")

    assert result is None
    assert not any("get_article: db error" in r.message for r in caplog.records)


# --- get_article_with_edition --------------------------------------------------


class _FakeCursor:
    """Minimal cursor that returns a canned fetchone() result for a single
    SQL execute. Sufficient for exercising get_article_with_edition's
    happy path / missing-edition branches without a real Postgres."""

    def __init__(self, row: tuple[str, str, int | None, int | None] | None) -> None:
        self._row = row

    def execute(self, _sql: str, _params: tuple[str, ...]) -> None:
        return None

    def fetchone(self) -> tuple[str, str, int | None, int | None] | None:
        return self._row

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _FakePool:
    """Stand-in ConnectionPool returning a canned fetchone() row."""

    def __init__(
        self, row: tuple[str, str, int | None, int | None] | None
    ) -> None:
        self._row = row

    def connection(self) -> _FakeConnection:
        return _FakeConnection(_FakeCursor(self._row))


def test_get_article_with_edition_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _FakePool(
        ("https://origin.example.com/article", "user-1", 42, 2)
    )
    monkeypatch.setattr(db_module, "_pool", pool)

    result = db_module.get_article_with_edition(ARTICLE_ID)

    assert result == {
        "url": "https://origin.example.com/article",
        "user_id": "user-1",
        "issue_no": 42,
        "position_in_edition": 2,
    }


def test_get_article_with_edition_returns_none_when_row_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Article id not found → fetchone() returns None → function returns None."""
    monkeypatch.setattr(db_module, "_pool", _FakePool(None))

    assert db_module.get_article_with_edition(ARTICLE_ID) is None


def test_get_article_with_edition_returns_partial_when_edition_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Article exists but edition_id is NULL / orphan: issue_no &
    position_in_edition come back as NULL → caller decides fallback."""
    pool = _FakePool(
        ("https://origin.example.com/article", "user-1", None, None)
    )
    monkeypatch.setattr(db_module, "_pool", pool)

    result = db_module.get_article_with_edition(ARTICLE_ID)

    assert result is not None
    assert result["issue_no"] is None
    assert result["position_in_edition"] is None


def test_get_article_with_edition_returns_none_on_operational_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neon cold start: psycopg.OperationalError must be swallowed → None,
    and the error must be logged (mirror get_article's contract)."""
    fake_pool = _PoolRaising(psycopg.OperationalError("connection closed"))
    monkeypatch.setattr(db_module, "_pool", fake_pool)

    with caplog.at_level(logging.ERROR, logger="app.db"):
        result = db_module.get_article_with_edition(ARTICLE_ID)

    assert result is None
    assert any(
        "get_article_with_edition: db error" in r.message and ARTICLE_ID in r.message
        for r in caplog.records
    )


def test_get_article_with_edition_returns_none_on_data_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed UUID: DataError silently → None, no error log."""
    fake_pool = _PoolRaising(psycopg.DataError("invalid input syntax for uuid"))
    monkeypatch.setattr(db_module, "_pool", fake_pool)

    with caplog.at_level(logging.ERROR, logger="app.db"):
        result = db_module.get_article_with_edition("not-a-uuid")

    assert result is None
    assert not any(
        "get_article_with_edition: db error" in r.message for r in caplog.records
    )
