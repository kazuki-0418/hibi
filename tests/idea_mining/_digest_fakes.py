"""Shared in-memory psycopg-shaped fakes for idea_mining digest tests.

`tests/idea_mining/test_critic.py` のスタイルを踏襲し、Neon の代わりに
``patterns`` / ``candidates`` テーブルを 2 つの list で表す軽量 fake を
公開する。pytest-postgres は導入しない (test-agent.md: 既存 fixture に
合わせる)。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PatternRow:
    id: str
    week_iso: str
    pain: str
    categories: list[str]
    frequency: int
    source_diversity: int
    confidence: float


@dataclass
class CandidateRow:
    id: int
    pattern_id: str
    name: str
    critic_verdict: str | None
    one_liner: str | None = None
    target_user: str | None = None
    monetization: str | None = None
    why_different: str | None = None
    killer_use_case: str | None = None
    critic_meta: dict[str, object] | None = None
    generated_at_rank: int = 0  # 大きいほど新しい (ORDER BY 用)


@dataclass
class _FakeStore:
    patterns: list[PatternRow] = field(default_factory=list)
    candidates: list[CandidateRow] = field(default_factory=list)


class _FakeCursor:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store
        self._result: list[tuple[object, ...]] = []
        self.rowcount: int = 0

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        normalized = " ".join(sql.split()).lower()
        if "from patterns where week_iso" in normalized:
            assert params is not None and len(params) == 2
            week_iso, limit = params
            assert isinstance(week_iso, str)
            assert isinstance(limit, int)
            matched = [p for p in self._store.patterns if p.week_iso == week_iso]
            # ORDER BY frequency DESC, pain ASC
            matched.sort(key=lambda p: (-p.frequency, p.pain))
            trimmed = matched[:limit]
            self._result = [
                (
                    p.id,
                    p.pain,
                    list(p.categories),
                    p.frequency,
                    p.source_diversity,
                    p.confidence,
                )
                for p in trimmed
            ]
            self.rowcount = len(self._result)
            return

        if (
            "from candidates where pattern_id" in normalized
            and "critic_verdict is not null" in normalized
        ):
            assert params is not None and len(params) == 1
            (pattern_id,) = params
            matched = [
                c
                for c in self._store.candidates
                if c.pattern_id == pattern_id and c.critic_verdict is not None
            ]
            # ORDER BY generated_at DESC, id DESC
            matched.sort(key=lambda c: (-c.generated_at_rank, -c.id))
            self._result = [
                (
                    c.id,
                    c.name,
                    c.one_liner,
                    c.target_user,
                    c.monetization,
                    c.why_different,
                    c.killer_use_case,
                    c.critic_verdict,
                    c.critic_meta,
                )
                for c in matched
            ]
            self.rowcount = len(self._result)
            return

        raise AssertionError(f"unexpected SQL in fake cursor: {sql!r}")

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._result)

    def fetchone(self) -> tuple[object, ...] | None:
        return self._result[0] if self._result else None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeConn:
    """Minimal psycopg.Connection stand-in for digest unit tests."""

    def __init__(
        self,
        *,
        patterns: list[PatternRow] | None = None,
        candidates: list[CandidateRow] | None = None,
    ) -> None:
        self._store = _FakeStore(
            patterns=list(patterns or []),
            candidates=list(candidates or []),
        )

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._store)

    def commit(self) -> None:
        return None
