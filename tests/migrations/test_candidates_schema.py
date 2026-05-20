"""Migration 010 (`candidates`) schema check — SQL string contract.

本テストは Neon を起動せず、`migrations/010_create_candidates.sql` の
文字列内容のみを検証する。actual schema 適用は Neon SQL Editor で手動。

Issue #138 acceptance: candidates テーブルが additive で新規作成され、
patterns(id) (uuid) への FK / monetization CHECK / llm_moat_conditions の
text[] 制約 / critic_verdict 候補値が migration ファイルに含まれる。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "migrations" / "010_create_candidates.sql"


def _sql_lower() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8").lower()


def test_migration_010_creates_candidates_table_idempotently() -> None:
    assert MIGRATION_PATH.is_file(), f"missing migration file: {MIGRATION_PATH}"
    sql = _sql_lower()
    assert "create table if not exists candidates" in sql


def test_migration_010_lists_all_required_columns() -> None:
    sql = _sql_lower()
    for col in (
        "id",
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
        "generated_at",
        "critic_verdict",
        "critic_meta",
    ):
        assert col in sql, f"migration 010 missing column: {col}"


def test_migration_010_uses_bigserial_pk() -> None:
    sql = _sql_lower()
    assert re.search(r"\bid\s+bigserial\s+primary\s+key", sql), sql


def test_migration_010_pattern_id_is_uuid_fk_to_patterns() -> None:
    sql = _sql_lower()
    # pattern_id must be uuid (NOT BIGINT as the Issue draft DDL had — patterns.id is uuid).
    assert re.search(
        r"pattern_id\s+uuid\s+not\s+null\s+references\s+patterns\s*\(\s*id\s*\)",
        sql,
    ), sql


def test_migration_010_spot_id_is_nullable_bigint() -> None:
    sql = _sql_lower()
    # Phase 0: nullable bigint, no FK yet.
    assert re.search(r"spot_id\s+bigint(?!\s+not\s+null)", sql), sql
    assert "references spots" not in sql


def test_migration_010_name_is_not_null() -> None:
    sql = _sql_lower()
    assert re.search(r"\bname\s+text\s+not\s+null", sql), sql


def test_migration_010_llm_moat_conditions_is_text_array_not_null() -> None:
    sql = _sql_lower()
    assert re.search(
        r"llm_moat_conditions\s+text\[\]\s+not\s+null", sql
    ), sql


def test_migration_010_generated_at_defaults_to_now() -> None:
    sql = _sql_lower()
    assert re.search(
        r"generated_at\s+timestamptz\s+not\s+null\s+default\s+now\(\)",
        sql,
    ), sql


def test_migration_010_critic_fields_remain_nullable() -> None:
    sql = _sql_lower()
    # critic_verdict / critic_meta have no NOT NULL — Issue #139 will write them.
    assert re.search(r"critic_verdict\s+text(?!\s+not\s+null)", sql), sql
    assert re.search(r"critic_meta\s+jsonb(?!\s+not\s+null)", sql), sql


def test_migration_010_enforces_monetization_enum() -> None:
    sql = _sql_lower()
    assert "candidates_monetization_chk" in sql
    for value in (
        "'subscription'",
        "'one-time'",
        "'affiliate'",
        "'freemium'",
        "'b2b'",
    ):
        assert value in sql, f"monetization check missing value: {value}"


def test_migration_010_enforces_critic_verdict_enum() -> None:
    sql = _sql_lower()
    assert "candidates_critic_verdict_chk" in sql
    for value in ("'go'", "'pending'", "'kill'"):
        assert value in sql, f"critic_verdict check missing value: {value}"


def test_migration_010_creates_helper_indexes() -> None:
    sql = _sql_lower()
    assert re.search(
        r"create index if not exists idx_candidates_pattern_id",
        sql,
    ), sql
    assert re.search(
        r"create index if not exists idx_candidates_generated_at",
        sql,
    ), sql


def test_migration_010_does_not_drop_or_alter_other_tables() -> None:
    """No destructive changes to existing tables (additive-only constraint)."""
    sql = _sql_lower()
    assert "drop table" not in sql
    # ALTER TABLE candidates ... is fine (own table), but never alter
    # patterns/articles/voices.
    assert "alter table patterns" not in sql
    assert "alter table articles" not in sql
    assert "alter table voices" not in sql
