"""Unit tests for db.get_stats_summary (Issue #54).

The actual VIEW lives in migrations/006_stats_summary_view.sql and is
applied to Neon out-of-band. These tests only verify the Python wrapper:
- it issues the expected query against ``stats_summary``,
- it maps the 3-column row to a typed dict,
- it returns zeros when the view returns no rows (defensive — should not
  happen in practice because the VIEW always projects exactly 1 row).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import db


class _FakeCursor:
    def __init__(self, row: tuple[int, int, int] | None) -> None:
        self.row = row
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[int, int, int] | None:
        return self.row


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _patch_get_conn(monkeypatch, cursor: _FakeCursor) -> None:
    monkeypatch.setattr(db, "get_conn", lambda: _FakeConn(cursor))


def test_returns_typed_dict_from_view_row(monkeypatch) -> None:
    cursor = _FakeCursor(row=(142, 710, 28))
    _patch_get_conn(monkeypatch, cursor)

    out = db.get_stats_summary()

    assert out == {
        "editions_count": 142,
        "stories_count": 710,
        "sources_count": 28,
    }


def test_query_targets_stats_summary_view(monkeypatch) -> None:
    cursor = _FakeCursor(row=(0, 0, 0))
    _patch_get_conn(monkeypatch, cursor)

    db.get_stats_summary()

    assert len(cursor.executed) == 1
    sql, _ = cursor.executed[0]
    assert "stats_summary" in sql
    # All three projected columns are read out.
    for col in ("editions_count", "stories_count", "sources_count"):
        assert col in sql


def test_returns_zeros_when_view_returns_no_row(monkeypatch) -> None:
    """Defensive: the view always returns 1 row in practice, but if the
    DB call returns None (e.g. transient transport oddity), do not crash —
    the masthead can render zeros without 500-ing."""
    cursor = _FakeCursor(row=None)
    _patch_get_conn(monkeypatch, cursor)

    out = db.get_stats_summary()

    assert out == {
        "editions_count": 0,
        "stories_count": 0,
        "sources_count": 0,
    }


def test_coerces_view_values_to_int(monkeypatch) -> None:
    """The view casts to ::int already, but psycopg may return numerics in
    some drivers — make sure the wrapper coerces uniformly."""
    cursor = _FakeCursor(row=(MagicMock(__int__=lambda _self: 5), 9, 2))
    _patch_get_conn(monkeypatch, cursor)

    out = db.get_stats_summary()

    assert out["editions_count"] == 5
    assert isinstance(out["editions_count"], int)
