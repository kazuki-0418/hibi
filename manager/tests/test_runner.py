"""End-to-end runner tests with DummySubagent / DummyGitOps / DummyEscalator."""

from __future__ import annotations

from pathlib import Path

import pytest

from manager.escalate import DummyEscalator
from manager.git_ops import DummyGitOps, GitOpsError
from manager.limits import EXIT_HALTED, EXIT_NEEDS_HUMAN, EXIT_OK
from manager.runner import Runner
from manager.state_store import StateStore
from manager.subagent import DummySubagent, make_result


def _read(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / name).read_text(encoding="utf-8")


def _build(
    state_root: Path,
    repo_root: Path,
    *,
    children: list[int],
    scripted: dict[str, list],
    pr_urls: dict[str, str] | None = None,
    failures: dict[str, GitOpsError] | None = None,
) -> tuple[Runner, DummyEscalator, DummyGitOps]:
    default_prs = {f"epic/1-test-child-{c}": f"https://x/pr/{c}" for c in children}
    git_ops = DummyGitOps(
        child_listing={1: children},
        pr_urls=default_prs if pr_urls is None else pr_urls,
        issue_bodies={c: f"body of {c}" for c in children},
        failures=failures or {},
    )
    escalator = DummyEscalator()
    runner = Runner(
        state_store=StateStore(state_root),
        subagent=DummySubagent(scripted),
        git_ops=git_ops,
        escalator=escalator,
        repo_root=repo_root,
    )
    return runner, escalator, git_ops


def _happy_scripted(fixtures_dir: Path, n_children: int) -> dict[str, list]:
    return {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_ready.md")) for _ in range(n_children)],
        "/make-execution-packet": [make_result(_read(fixtures_dir, "packet_minimal.md")) for _ in range(n_children)],
        "/spec-architect": [make_result(_read(fixtures_dir, "plan_proceed.md")) for _ in range(n_children)],
        "/run-dev-loop": [make_result(_read(fixtures_dir, "dev_loop_safe.md")) for _ in range(n_children)],
    }


def test_happy_path_two_children(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    runner, escalator, _git = _build(
        state_root, repo_root, children=[10, 11],
        scripted=_happy_scripted(fixtures_dir, 2),
    )
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_OK

    epic = runner.state_store.load_epic(1)
    assert epic["status"] == "DONE"
    assert epic["children_done"] == [10, 11]
    assert epic["children_failed"] == []
    assert epic["children_queue"] == []

    for c in (10, 11):
        child = runner.state_store.load_child(1, c)
        assert child["status"] == "DONE"
        assert child["pr_url"] == f"https://x/pr/{c}"
        assert child["last_verdict"] == "safe to merge"

    assert any("finished epic" in body for _, body in escalator.posted)


def test_skip_on_do_not_run(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    scripted = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_skip.md"))],
        # No subsequent calls expected — DummySubagent would raise if invoked.
    }
    runner, _esc, _git = _build(state_root, repo_root, children=[10], scripted=scripted)
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_OK
    epic = runner.state_store.load_epic(1)
    assert epic["children_skipped"] == [10]
    assert epic["children_done"] == []


def test_needs_confirmation_escalates(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    scripted = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_needs_confirmation.md"))],
    }
    runner, escalator, _git = _build(
        state_root, repo_root, children=[10], scripted=scripted
    )
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_NEEDS_HUMAN
    child = runner.state_store.load_child(1, 10)
    assert child["status"] == "NEEDS_HUMAN"
    assert "needs-confirmation" in (child["needs_human_reason"] or "")
    assert any("halted on child" in body for _, body in escalator.posted)


def test_plan_confirm_first_escalates(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    scripted = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_ready.md"))],
        "/make-execution-packet": [make_result(_read(fixtures_dir, "packet_minimal.md"))],
        "/spec-architect": [make_result(_read(fixtures_dir, "plan_confirm.md"))],
    }
    runner, _esc, _git = _build(state_root, repo_root, children=[10], scripted=scripted)
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_NEEDS_HUMAN
    child = runner.state_store.load_child(1, 10)
    assert child["status"] == "NEEDS_HUMAN"
    assert "confirm first" in (child["needs_human_reason"] or "")


def test_implement_fix_then_safe_succeeds(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    """fix before merge first, then safe to merge — must DONE."""
    scripted = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_ready.md"))],
        "/make-execution-packet": [make_result(_read(fixtures_dir, "packet_minimal.md"))],
        "/spec-architect": [make_result(_read(fixtures_dir, "plan_proceed.md"))],
        "/run-dev-loop": [
            make_result(_read(fixtures_dir, "dev_loop_fix.md")),
            make_result(_read(fixtures_dir, "dev_loop_safe.md")),
        ],
    }
    runner, _esc, _git = _build(state_root, repo_root, children=[10], scripted=scripted)
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_OK
    child = runner.state_store.load_child(1, 10)
    assert child["status"] == "DONE"
    assert child["retry"]["implement"] == 1


def test_implement_fix_exhausts_retry_then_escalates(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    fix = _read(fixtures_dir, "dev_loop_fix.md")
    scripted = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_ready.md"))],
        "/make-execution-packet": [make_result(_read(fixtures_dir, "packet_minimal.md"))],
        "/spec-architect": [make_result(_read(fixtures_dir, "plan_proceed.md"))],
        "/run-dev-loop": [
            make_result(fix), make_result(fix), make_result(fix), make_result(fix),
        ],  # 1 initial + 3 retries (limit) + 1 to trigger escalation
    }
    runner, _esc, _git = _build(state_root, repo_root, children=[10], scripted=scripted)
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_NEEDS_HUMAN
    child = runner.state_store.load_child(1, 10)
    assert child["status"] == "NEEDS_HUMAN"
    assert "retry exhausted" in (child["needs_human_reason"] or "")


def test_dev_loop_blocked_treated_as_confirm(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    scripted = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_ready.md"))],
        "/make-execution-packet": [make_result(_read(fixtures_dir, "packet_minimal.md"))],
        "/spec-architect": [make_result(_read(fixtures_dir, "plan_proceed.md"))],
        "/run-dev-loop": [make_result(_read(fixtures_dir, "dev_loop_blocked.md"))],
    }
    runner, _esc, _git = _build(state_root, repo_root, children=[10], scripted=scripted)
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_NEEDS_HUMAN
    child = runner.state_store.load_child(1, 10)
    assert child["status"] == "NEEDS_HUMAN"
    assert child["last_verdict"] == "confirm before merge"


def test_kill_switch_halts(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    (repo_root / ".claude" / "STOP").write_text("halt please", encoding="utf-8")
    scripted = _happy_scripted(fixtures_dir, 1)
    runner, escalator, _git = _build(
        state_root, repo_root, children=[10], scripted=scripted
    )
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_HALTED
    epic = runner.state_store.load_epic(1)
    assert epic["status"] == "HALTED"
    assert any("halted epic" in body for _, body in escalator.posted)


def test_pr_not_found_retries_then_escalates(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    scripted = _happy_scripted(fixtures_dir, 1)
    runner, _esc, _git = _build(
        state_root, repo_root, children=[10],
        scripted=scripted,
        pr_urls={},  # gh finds nothing
    )
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_NEEDS_HUMAN
    child = runner.state_store.load_child(1, 10)
    assert child["status"] == "NEEDS_HUMAN"
    assert "PR not found" in (child["needs_human_reason"] or "")
    assert child["retry"]["verify_pr"] == 3


def test_no_children_halts(state_root: Path, repo_root: Path) -> None:
    runner, escalator, _git = _build(state_root, repo_root, children=[], scripted={})
    rc = runner.run_epic(1, slug="test")
    assert rc == EXIT_HALTED
    assert any("no child issues" in body for _, body in escalator.posted)


def test_artifacts_persisted(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    scripted = _happy_scripted(fixtures_dir, 1)
    runner, _esc, _git = _build(state_root, repo_root, children=[10], scripted=scripted)
    runner.run_epic(1, slug="test")
    child_dir = runner.state_store.child_dir(1, 10)
    for name in ("issue.txt", "triage.md", "packet.yaml", "plan.md", "dev_loop.md"):
        assert (child_dir / name).exists(), f"missing artifact: {name}"
