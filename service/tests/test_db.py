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
