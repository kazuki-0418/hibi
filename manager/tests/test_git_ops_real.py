from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from manager import git_ops as git_mod
from manager._subprocess import CommandResult
from manager.git_ops import GitOpsError, RealGitOps, parse_children_from_body


def test_parse_children_from_body_extracts_in_order() -> None:
    body = """\
# Epic: Add 3 fetchers

## Goal
Cover 3 missing sources.

## Children
- #11 add fetcher A
- #12 add fetcher B
- #13 add fetcher C

## Notes
- references #99 (not a child, in a different section)
"""
    assert parse_children_from_body(body) == [11, 12, 13]


def test_parse_children_from_body_dedupes() -> None:
    body = "## Children\n- #5 first\n- #5 dupe\n- #6 next\n"
    assert parse_children_from_body(body) == [5, 6]


def test_parse_children_from_body_returns_empty_when_section_missing() -> None:
    assert parse_children_from_body("## Goal\nno children listed\n") == []


def test_parse_children_from_body_japanese_heading() -> None:
    body = """\
## 背景
foo

## 子 Issue

- [ ] #40 feat(email): rewrite digest template
- [ ] #41 feat(web): edition page
- [ ] #42 feat(web): archive index

## 非交渉ルール
- something else with #99
"""
    assert parse_children_from_body(body) == [40, 41, 42]


class _FakeRunner:
    """Records calls; returns scripted CommandResult per (binary, first-arg) pair."""

    def __init__(self, scripted: dict[tuple[str, ...], CommandResult]) -> None:
        self.scripted = scripted
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        stdin: str | None = None,
        timeout: int = 0,
        cwd: str | None = None,
    ) -> CommandResult:
        argv_list = list(argv)
        self.calls.append(argv_list)
        for key, result in self.scripted.items():
            if tuple(argv_list[: len(key)]) == key:
                return result
        # Default: success with empty stdout.
        return CommandResult(exit_code=0, stdout="", stderr="", elapsed_seconds=0.0)


def _patch(monkeypatch: pytest.MonkeyPatch, runner: _FakeRunner) -> None:
    monkeypatch.setattr(git_mod, "run", runner)


def test_create_epic_branch_when_not_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = _FakeRunner({
        ("git", "fetch", "origin", "main"): CommandResult(0, "", "", 0.0),
        ("git", "rev-parse", "--verify", "--quiet", "epic/42-foo"):
            CommandResult(1, "", "", 0.0),
        ("git", "checkout", "-b", "epic/42-foo", "origin/main"):
            CommandResult(0, "", "", 0.0),
    })
    _patch(monkeypatch, runner)
    ops = RealGitOps(repo_root=tmp_path)
    branch = ops.create_epic_branch(42, "foo")
    assert branch == "epic/42-foo"
    bins = [c[0] for c in runner.calls]
    assert bins.count("git") == 3
    # Idempotent path NOT taken (no plain `checkout` call).
    assert ["git", "checkout", "epic/42-foo"] not in runner.calls


def test_create_epic_branch_idempotent_when_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _FakeRunner({
        ("git", "rev-parse", "--verify", "--quiet", "epic/42-foo"):
            CommandResult(0, "deadbeef\n", "", 0.0),
    })
    _patch(monkeypatch, runner)
    ops = RealGitOps(repo_root=tmp_path)
    branch = ops.create_epic_branch(42, "foo")
    assert branch == "epic/42-foo"
    assert ["git", "checkout", "epic/42-foo"] in runner.calls
    assert not any("checkout" in c and "-b" in c for c in runner.calls)


def test_create_epic_branch_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _FakeRunner({
        ("git", "fetch", "origin", "main"):
            CommandResult(128, "", "could not fetch", 0.0),
    })
    _patch(monkeypatch, runner)
    ops = RealGitOps(repo_root=tmp_path)
    with pytest.raises(GitOpsError) as exc:
        ops.create_epic_branch(42, "foo")
    assert "fetch" in str(exc.value)


def test_create_child_branch_off_epic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = _FakeRunner({
        ("git", "rev-parse", "--verify", "--quiet", "epic/42-foo-child-7"):
            CommandResult(1, "", "", 0.0),
    })
    _patch(monkeypatch, runner)
    ops = RealGitOps(repo_root=tmp_path)
    branch = ops.create_child_branch("epic/42-foo", 7)
    assert branch == "epic/42-foo-child-7"
    assert ["git", "checkout", "epic/42-foo"] in runner.calls
    assert ["git", "checkout", "-b", "epic/42-foo-child-7"] in runner.calls


def test_child_branch_name_does_not_use_slash() -> None:
    """git rejects `refs/heads/X` and `refs/heads/X/Y` coexisting."""
    from manager.git_ops import child_branch_name
    name = child_branch_name("epic/39-design-system", 40)
    assert name == "epic/39-design-system-child-40"
    assert "/child-" not in name


def test_diff_lines_sums_numstat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    numstat = "10\t2\tfoo.py\n5\t0\tbar.py\n-\t-\timg.png\n"
    runner = _FakeRunner({
        ("git", "diff", "--numstat", "main...HEAD"):
            CommandResult(0, numstat, "", 0.0),
    })
    _patch(monkeypatch, runner)
    ops = RealGitOps(repo_root=tmp_path)
    assert ops.diff_lines("main") == 17


def test_diff_lines_returns_zero_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _FakeRunner({
        ("git", "diff", "--numstat", "main...HEAD"):
            CommandResult(128, "", "bad refs", 0.0),
    })
    _patch(monkeypatch, runner)
    assert RealGitOps(repo_root=tmp_path).diff_lines("main") == 0


def test_find_pr_url_returns_url_or_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _FakeRunner({
        ("gh", "pr", "list", "--head", "branch-with-pr"):
            CommandResult(0, "https://github.com/x/repo/pull/123\n", "", 0.0),
        ("gh", "pr", "list", "--head", "branch-without-pr"):
            CommandResult(0, "\n", "", 0.0),
    })
    _patch(monkeypatch, runner)
    ops = RealGitOps(repo_root=tmp_path)
    assert ops.find_pr_url("branch-with-pr", "epic/x") == "https://github.com/x/repo/pull/123"
    assert ops.find_pr_url("branch-without-pr", "epic/x") is None


def test_find_pr_url_does_not_filter_by_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Phase 3 limitation: /pr-creation forces base=main, so we accept any base."""
    runner = _FakeRunner({})
    _patch(monkeypatch, runner)
    RealGitOps(repo_root=tmp_path).find_pr_url("any-branch", "epic/x")
    # `--base epic/x` must NOT be in the gh argv.
    assert all("--base" not in c for c in runner.calls)


def test_fetch_issue_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = _FakeRunner({
        ("gh", "issue", "view", "42"):
            CommandResult(0, "issue body text", "", 0.0),
    })
    _patch(monkeypatch, runner)
    assert RealGitOps(repo_root=tmp_path).fetch_issue_body(42) == "issue body text"


def test_list_child_issues_parses_epic_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = "## Goal\nx\n## Children\n- #11 a\n- #12 b\n## Notes\n- ref #99\n"
    runner = _FakeRunner({
        ("gh", "issue", "view", "42"): CommandResult(0, body, "", 0.0),
    })
    _patch(monkeypatch, runner)
    assert RealGitOps(repo_root=tmp_path).list_child_issues(42) == [11, 12]
