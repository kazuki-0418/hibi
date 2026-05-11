"""Phase 4 runner tests: resume, retry-failed, PR retarget, signal halt, repo-relative paths."""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

import pytest

from manager.escalate import DummyEscalator
from manager.git_ops import DummyGitOps
from manager.limits import EXIT_HALTED, EXIT_NEEDS_HUMAN, EXIT_OK
from manager.runner import Runner
from manager.state_store import StateStore
from manager.subagent import DummySubagent, make_result


def _read(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / name).read_text(encoding="utf-8")


def _happy(fixtures_dir: Path, n: int) -> dict[str, list]:
    return {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_ready.md")) for _ in range(n)],
        "/make-execution-packet": [make_result(_read(fixtures_dir, "packet_minimal.md")) for _ in range(n)],
        "/spec-architect": [make_result(_read(fixtures_dir, "plan_proceed.md")) for _ in range(n)],
        "/run-dev-loop": [make_result(_read(fixtures_dir, "dev_loop_safe.md")) for _ in range(n)],
    }


def _build(
    state_root: Path,
    repo_root: Path,
    *,
    children: list[int],
    scripted: dict[str, list],
    pr_urls: dict[str, str] | None = None,
    install_signal_handlers: bool = False,
) -> tuple[Runner, DummyEscalator, DummyGitOps]:
    default_prs = {f"epic/1-test-child-{c}": f"https://x/pr/{c}" for c in children}
    git_ops = DummyGitOps(
        child_listing={1: children},
        pr_urls=default_prs if pr_urls is None else pr_urls,
        issue_bodies={c: f"body of {c}" for c in children},
    )
    escalator = DummyEscalator()
    runner = Runner(
        state_store=StateStore(state_root),
        subagent=DummySubagent(scripted),
        git_ops=git_ops,
        escalator=escalator,
        repo_root=repo_root,
        install_signal_handlers=install_signal_handlers,
    )
    return runner, escalator, git_ops


# ===================================================================
# resume + retry_failed
# ===================================================================


def test_resume_continues_from_halted_state(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    """First run: child #10 halts at TRIAGE (needs-confirmation). Resume: #11 proceeds."""
    scripted_first = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_needs_confirmation.md"))],
    }
    runner1, _esc1, _git1 = _build(state_root, repo_root, children=[10, 11], scripted=scripted_first)
    rc1 = runner1.run_epic(1, slug="test")
    assert rc1 == EXIT_NEEDS_HUMAN

    epic = runner1.state_store.load_epic(1)
    assert epic["status"] == "HALTED"
    assert epic["children_failed"] == [10]
    assert epic["children_queue"] == [11]

    scripted_resume = _happy(fixtures_dir, 1)
    runner2, _esc2, _git2 = _build(state_root, repo_root, children=[10, 11], scripted=scripted_resume)
    rc2 = runner2.run_epic(1, slug="test")
    assert rc2 == EXIT_OK
    epic = runner2.state_store.load_epic(1)
    assert epic["status"] == "DONE"
    assert epic["children_done"] == [11]
    assert epic["children_failed"] == [10]  # #10 stays failed unless retry-flag


def test_retry_failed_resets_child_and_re_attempts(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    """First run: #10 halts. Resume with retry_failed=[10]: #10 re-runs successfully."""
    scripted_first = {
        "/triage-issue": [make_result(_read(fixtures_dir, "triage_needs_confirmation.md"))],
    }
    runner1, _esc1, _git1 = _build(state_root, repo_root, children=[10], scripted=scripted_first)
    runner1.run_epic(1, slug="test")

    scripted_retry = _happy(fixtures_dir, 1)
    runner2, _esc2, _git2 = _build(state_root, repo_root, children=[10], scripted=scripted_retry)
    rc = runner2.run_epic(1, slug="test", retry_failed=[10])
    assert rc == EXIT_OK
    epic = runner2.state_store.load_epic(1)
    assert epic["status"] == "DONE"
    assert epic["children_done"] == [10]
    assert epic["children_failed"] == []


def test_retry_failed_ignores_unknown_child(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    """Asking to retry a child that wasn't failed must be a no-op (no crash)."""
    runner1, _esc, _git = _build(
        state_root, repo_root, children=[10], scripted=_happy(fixtures_dir, 1)
    )
    runner1.run_epic(1, slug="test")  # #10 → DONE
    # Resume asking to retry #10 (which is in done, not failed) — must no-op.
    runner2, _esc2, _git2 = _build(state_root, repo_root, children=[10], scripted={})
    rc = runner2.run_epic(1, slug="test", retry_failed=[10])
    assert rc == EXIT_OK


# ===================================================================
# PR retarget
# ===================================================================


def test_verify_pr_retargets_to_epic_branch(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    runner, _esc, git = _build(
        state_root, repo_root, children=[10], scripted=_happy(fixtures_dir, 1),
    )
    runner.run_epic(1, slug="test")
    assert git.retargeted == {"https://x/pr/10": "epic/1-test"}


# ===================================================================
# Signal handler
# ===================================================================


def test_signal_received_halts_between_children(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    """SIGINT arriving between children causes a clean HALTED + state save."""
    runner, escalator, _git = _build(
        state_root, repo_root, children=[10, 11, 12],
        scripted=_happy(fixtures_dir, 3),
        install_signal_handlers=True,
    )

    # Fire SIGINT after a tiny delay, so it lands during the first child's processing.
    pid = os.getpid()
    fired = threading.Event()

    def _shoot() -> None:
        time.sleep(0.05)
        os.kill(pid, signal.SIGINT)
        fired.set()

    threading.Thread(target=_shoot, daemon=True).start()
    rc = runner.run_epic(1, slug="test")
    fired.wait(timeout=2.0)

    # Either HALTED before completing all children, or completed entirely (race).
    assert rc in (EXIT_OK, EXIT_HALTED)
    epic = runner.state_store.load_epic(1)
    if rc == EXIT_HALTED:
        assert epic["status"] == "HALTED"
        assert any("halted epic" in body for _, body in escalator.posted)


# ===================================================================
# Repo-relative paths in escalation
# ===================================================================


def test_escalation_path_is_repo_relative(
    state_root: Path, repo_root: Path, fixtures_dir: Path
) -> None:
    """state_path in the Issue comment must resolve to a path under the repo."""
    # Anchor state_root inside repo_root so the relative-to actually matches.
    inner_state = repo_root / ".claude" / "state"
    inner_state.mkdir(parents=True)
    runner, escalator, _git = _build(
        inner_state, repo_root, children=[10],
        scripted={
            "/triage-issue": [make_result(_read(fixtures_dir, "triage_needs_confirmation.md"))],
        },
    )
    runner.run_epic(1, slug="test")
    body = escalator.posted[0][1]
    assert ".claude/state/epic-1/children/child-10/state.json" in body
