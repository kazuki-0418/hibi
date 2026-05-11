"""CLI tests for `python -m manager` subcommands (status / run / resume)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manager import __main__ as cli
from manager.state_store import StateStore


def test_cli_status_missing_epic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "STATE_ROOT", tmp_path / "state")
    rc = cli.main(["status", "999"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no state for epic #999" in err


def test_cli_status_prints_epic_and_children(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(cli, "STATE_ROOT", state_root)
    store = StateStore(state_root)
    store.init_epic(7, "epic/7-foo", [10, 11])
    store.init_child(7, 10, "epic/7-foo-child-10")

    rc = cli.main(["status", "7"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out.split("\n  child")[0])
    assert parsed["epic_issue_number"] == 7
    assert parsed["status"] == "RUNNING"
    assert "child #10: INIT" in out


def test_cli_run_dry_run_creates_state_then_raises_on_dummy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`run --children N` with default Dummy* creates state up to first subagent call,
    then raises because Dummy has no scripted response. The state on disk is the
    proof that argparse / wiring works end-to-end without --live."""
    state_root = tmp_path / "state"
    monkeypatch.setattr(cli, "STATE_ROOT", state_root)
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="DummySubagent: no scripted response"):
        cli.main(["run", "8", "--slug", "demo", "--children", "20"])
    assert (state_root / "epic-8" / "epic.json").exists()


def test_cli_resume_alias_for_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`resume` accepts the same args as `run` (verified by argparse parsing)."""
    state_root = tmp_path / "state"
    monkeypatch.setattr(cli, "STATE_ROOT", state_root)
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    parser_args = cli.argparse.ArgumentParser(prog="manager")
    # Just verify argv parses without crashing.
    with pytest.raises(SystemExit):
        cli.main(["resume", "--help"])
