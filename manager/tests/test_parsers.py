from __future__ import annotations

from pathlib import Path

import pytest

from manager.parsers import ParseError
from manager.parsers.dev_loop import parse_dev_loop
from manager.parsers.packet import parse_packet
from manager.parsers.plan import parse_plan
from manager.parsers.triage import parse_classification, parse_triage


def _read(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / name).read_text(encoding="utf-8")


def test_parse_triage_ready(fixtures_dir: Path) -> None:
    assert parse_triage(_read(fixtures_dir, "triage_ready.md")) == "ready"
    assert parse_classification(_read(fixtures_dir, "triage_ready.md")) == "auto-fixable"


def test_parse_triage_skip(fixtures_dir: Path) -> None:
    assert parse_triage(_read(fixtures_dir, "triage_skip.md")) == "do-not-run"


def test_parse_triage_needs_confirmation(fixtures_dir: Path) -> None:
    assert (
        parse_triage(_read(fixtures_dir, "triage_needs_confirmation.md"))
        == "needs-confirmation"
    )


def test_parse_triage_missing_section_raises() -> None:
    with pytest.raises(ParseError):
        parse_triage("# Some Other Section\n- ready\n")


def test_parse_packet_minimal(fixtures_dir: Path) -> None:
    parsed = parse_packet(_read(fixtures_dir, "packet_minimal.md"))
    assert parsed["issue_id"] == 101
    assert parsed["scope"] == "small"


def test_parse_packet_missing_required_raises() -> None:
    with pytest.raises(ParseError) as exc:
        parse_packet("```yaml\nissue_id: 1\ntitle: x\n```")
    assert "必須フィールド欠落" in str(exc.value)


def test_parse_plan_proceed(fixtures_dir: Path) -> None:
    assert parse_plan(_read(fixtures_dir, "plan_proceed.md")) == "proceed"


def test_parse_plan_confirm(fixtures_dir: Path) -> None:
    assert parse_plan(_read(fixtures_dir, "plan_confirm.md")) == "confirm first"


def test_parse_plan_proceed_with_caution_backticked(fixtures_dir: Path) -> None:
    # /spec-architect は Recommendation 行の値を markdown コードスタイルで
    # 囲うことがある (`proceed with caution`)。バッククォートを許容する。
    assert (
        parse_plan(_read(fixtures_dir, "plan_proceed_with_caution_backticked.md"))
        == "proceed with caution"
    )


def test_parse_plan_missing_raises() -> None:
    with pytest.raises(ParseError):
        parse_plan("# Goal\nnothing")


def test_parse_dev_loop_safe_short_verdict_backticked(fixtures_dir: Path) -> None:
    # /run-dev-loop は header を `# Verdict` (公式 `# Review Verdict` を短縮)
    # かつ値を markdown コードスタイル (`safe to merge`) で出力することがある。
    # 両方を許容する。
    outcome = parse_dev_loop(
        _read(fixtures_dir, "dev_loop_safe_short_verdict_backticked.md")
    )
    assert outcome.verdict == "safe to merge"
    assert outcome.blocked is False


def test_parse_dev_loop_safe(fixtures_dir: Path) -> None:
    outcome = parse_dev_loop(_read(fixtures_dir, "dev_loop_safe.md"))
    assert outcome.verdict == "safe to merge"
    assert outcome.pytest_status == "Pytest Passed"
    assert outcome.dryrun_status == "Dry-run Passed"
    assert outcome.migration_status == "Migration N/A"
    assert outcome.pr_title == "feat: add example fetcher"
    assert outcome.blocked is False


def test_parse_dev_loop_fix(fixtures_dir: Path) -> None:
    outcome = parse_dev_loop(_read(fixtures_dir, "dev_loop_fix.md"))
    assert outcome.verdict == "fix before merge"
    assert outcome.pytest_status == "Pytest Failed"


def test_parse_dev_loop_confirm(fixtures_dir: Path) -> None:
    outcome = parse_dev_loop(_read(fixtures_dir, "dev_loop_confirm.md"))
    assert outcome.verdict == "confirm before merge"
    assert outcome.migration_status == "Migration Pending"


def test_parse_dev_loop_blocked(fixtures_dir: Path) -> None:
    outcome = parse_dev_loop(_read(fixtures_dir, "dev_loop_blocked.md"))
    assert outcome.blocked is True
    assert outcome.verdict == "confirm before merge"


def test_parse_dev_loop_missing_verdict_raises() -> None:
    with pytest.raises(ParseError):
        parse_dev_loop("# Implementation Summary\n## Pytest Status\n- Pytest Passed\n")
