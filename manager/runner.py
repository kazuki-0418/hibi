"""Manager runner: drives one epic through its state machine.

Synchronous. Side effects only via injected `subagent`, `git_ops`, `escalator`,
and `state_store` — that's what makes the state machine fully testable with the
Dummy* implementations.
"""

from __future__ import annotations

import signal
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .checkpoints import cost_check, diff_check, kill_switch
from .escalate import (
    Escalator,
    render_epic_done,
    render_halted,
    render_needs_human,
)
from .git_ops import GitOps, GitOpsError
from .limits import (
    EXIT_HALTED,
    EXIT_NEEDS_HUMAN,
    EXIT_OK,
    IMPLEMENT_MAX_ATTEMPTS,
    PACKETIZE_MAX_ATTEMPTS,
    PER_STAGE_BUDGET_USD,
    PLAN_MAX_ATTEMPTS,
    TRIAGE_MAX_ATTEMPTS,
    VERIFY_PR_MAX_ATTEMPTS,
)
from .parsers import ParseError
from .parsers.dev_loop import parse_dev_loop
from .parsers.packet import parse_packet
from .parsers.plan import parse_plan
from .parsers.triage import parse_triage
from .state_store import StateStore
from .states import TERMINAL_STATES, is_legal
from .subagent import Subagent, SubagentResult
from .types import (
    ChildState,
    ChildStatus,
    EpicState,
    RetryKey,
    get_retry,
    set_retry,
)


class _StopEpic(Exception):
    """Internal control-flow: bail out of the per-child loop into HALTED."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


Handler = Callable[["Runner", EpicState, ChildState], None]


@dataclass
class Runner:
    state_store: StateStore
    subagent: Subagent
    git_ops: GitOps
    escalator: Escalator
    repo_root: Path
    install_signal_handlers: bool = True
    _signal_received: bool = field(default=False, init=False, repr=False)

    # ----------------------------------------------------------------- entry

    def run_epic(
        self,
        epic_issue: int,
        slug: str,
        *,
        retry_failed: list[int] | None = None,
    ) -> int:
        """Run (or resume) one epic. If `retry_failed` is non-empty, those child
        issue numbers are reset to INIT and put back at the head of the queue.
        """
        retry_failed = retry_failed or []
        with self.state_store.epic_lock(epic_issue):
            with self._signal_guard():
                try:
                    epic = self._init_or_load_epic(epic_issue, slug)
                except _StopEpic as stop:
                    return self._finish_halted(_placeholder_epic(epic_issue), stop.reason)

                self._apply_retry_failed(epic, retry_failed)
                if epic["status"] == "HALTED":
                    epic["status"] = "RUNNING"
                    self.state_store.save_epic(epic)
                    self._log(epic_issue, {"event": "resumed", "queue": epic["children_queue"]})
                else:
                    self._log(epic_issue, {"event": "epic_start", "queue": epic["children_queue"]})

                try:
                    while epic["children_queue"]:
                        if self._signal_received:
                            raise _StopEpic("received SIGINT/SIGTERM")
                        child_issue = epic["children_queue"][0]
                        epic["current_child"] = child_issue
                        self.state_store.save_epic(epic)
                        terminal = self._run_child(epic, child_issue)
                        self._record_child_outcome(epic, child_issue, terminal)
                        self.state_store.save_epic(epic)
                        if terminal == "NEEDS_HUMAN":
                            return self._finish_needs_human(epic, child_issue)
                except _StopEpic as stop:
                    return self._finish_halted(epic, stop.reason)
                return self._finish_done(epic)

    def _init_or_load_epic(self, epic_issue: int, slug: str) -> EpicState:
        if self.state_store.epic_path(epic_issue).exists():
            return self.state_store.load_epic(epic_issue)
        children = self.git_ops.list_child_issues(epic_issue)
        if not children:
            raise _StopEpic(f"no child issues found for epic #{epic_issue}")
        try:
            epic_branch = self.git_ops.create_epic_branch(epic_issue, slug)
        except GitOpsError as exc:
            raise _StopEpic(f"failed to create epic branch: {exc}") from exc
        return self.state_store.init_epic(epic_issue, epic_branch, children)

    def _apply_retry_failed(self, epic: EpicState, retry_failed: list[int]) -> None:
        """Reset specified failed children and put them back at the head of the queue."""
        for child_issue in retry_failed:
            if child_issue not in epic["children_failed"]:
                continue
            child_path = self.state_store.child_path(epic["epic_issue_number"], child_issue)
            if child_path.exists():
                child_path.unlink()
            bak = child_path.with_suffix(child_path.suffix + ".bak")
            if bak.exists():
                bak.unlink()
            epic["children_failed"].remove(child_issue)
            epic["children_queue"].insert(0, child_issue)
            self._log(
                epic["epic_issue_number"],
                {"event": "retry_failed", "child": child_issue},
            )

    # ------------------------------------------------------------ per child

    def _run_child(self, epic: EpicState, child_issue: int) -> ChildStatus:
        epic_n = epic["epic_issue_number"]
        is_resume = self.state_store.child_path(epic_n, child_issue).exists()

        if is_resume:
            child = self.state_store.load_child(epic_n, child_issue)
            # Resume must re-checkout the child branch. Without this, every git
            # operation in this run (including `diff_lines` inside
            # `_guard_checkpoints`) measures from whatever branch the working
            # tree happens to be on — e.g. after manual state surgery or a
            # branch switch between Manager invocations — producing a phantom
            # diff that trips MAX_DIFF_LINES_PER_CHILD on the first iteration.
            # `create_child_branch` is idempotent: if the branch already
            # exists it just checks it out.
            if child["status"] not in TERMINAL_STATES:
                try:
                    self.git_ops.create_child_branch(epic["epic_branch"], child_issue)
                except GitOpsError as exc:
                    child["needs_human_reason"] = f"resume checkout failed: {exc}"
                    self.transition(epic, child, "NEEDS_HUMAN")
                    return "NEEDS_HUMAN"
        else:
            try:
                branch = self.git_ops.create_child_branch(epic["epic_branch"], child_issue)
            except GitOpsError as exc:
                child = self.state_store.init_child(epic_n, child_issue, branch="")
                child["needs_human_reason"] = f"create_child_branch failed: {exc}"
                self.transition(epic, child, "NEEDS_HUMAN")
                return "NEEDS_HUMAN"
            child = self.state_store.init_child(epic_n, child_issue, branch)

        if child["status"] == "INIT":
            self.transition(epic, child, "TRIAGE")

        while child["status"] not in TERMINAL_STATES:
            self._guard_checkpoints(epic, child)
            # _guard_checkpoints can transition status to NEEDS_HUMAN (diff cap
            # trip). Re-check before the handler lookup — without this, the
            # next line raises KeyError on `_HANDLERS["NEEDS_HUMAN"]` because
            # terminal states have no handler.
            if child["status"] in TERMINAL_STATES:
                break
            handler = _HANDLERS[child["status"]]
            handler(self, epic, child)

        return child["status"]

    # --------------------------------------------------------- checkpoints

    def _guard_checkpoints(self, epic: EpicState, child: ChildState) -> None:
        kill = kill_switch(self.repo_root)
        if kill.tripped:
            raise _StopEpic(kill.reason)
        cost = cost_check(epic["cost_usd"])
        if cost.tripped:
            raise _StopEpic(cost.reason)
        diff = diff_check(self.git_ops.diff_lines(epic["epic_branch"]))
        if diff.tripped:
            child["needs_human_reason"] = diff.reason
            self.transition(epic, child, "NEEDS_HUMAN")

    # ------------------------------------------------------------- helpers

    def transition(self, epic: EpicState, child: ChildState, dst: ChildStatus) -> None:
        src = child["status"]
        if src == dst:
            return
        if not is_legal(src, dst):
            raise AssertionError(f"illegal transition: {src} -> {dst}")
        child["status"] = dst
        self.state_store.save_child(epic["epic_issue_number"], child)
        self._log(
            epic["epic_issue_number"],
            {"event": "transition", "child": child["issue_number"], "from": src, "to": dst},
        )

    def record_subagent(
        self,
        epic: EpicState,
        child: ChildState,
        slash: str,
        result: SubagentResult,
        artifact_name: str,
    ) -> Path:
        child["cost_usd"] += result.cost_usd
        epic["cost_usd"] += result.cost_usd
        path = self.state_store.write_artifact(
            epic["epic_issue_number"],
            child["issue_number"],
            artifact_name,
            result.raw_stdout,
        )
        child["artifacts"][artifact_name] = str(path.relative_to(self.state_store.root))
        self.state_store.save_child(epic["epic_issue_number"], child)
        self.state_store.save_epic(epic)
        self._log(
            epic["epic_issue_number"],
            {
                "event": "subagent",
                "child": child["issue_number"],
                "slash": slash,
                "exit_code": result.exit_code,
                "session_id": result.session_id,
                "cost_usd": result.cost_usd,
            },
        )
        return path

    def _record_child_outcome(
        self,
        epic: EpicState,
        child_issue: int,
        terminal: ChildStatus,
    ) -> None:
        if epic["children_queue"] and epic["children_queue"][0] == child_issue:
            epic["children_queue"].pop(0)
        if terminal == "DONE":
            epic["children_done"].append(child_issue)
        elif terminal == "SKIPPED":
            epic["children_skipped"].append(child_issue)
        elif terminal == "NEEDS_HUMAN":
            epic["children_failed"].append(child_issue)
        epic["current_child"] = None

    def _log(self, epic_issue: int, event: dict[str, object]) -> None:
        self.state_store.append_log(epic_issue, event)

    # --------------------------------------------------------- signals

    @contextmanager
    def _signal_guard(self) -> Iterator[None]:
        """Install SIGINT/SIGTERM handlers that flip a flag instead of killing.

        The flag is checked before each child so the current handler completes
        and state is saved before exit. Restored on context exit.
        """
        if not self.install_signal_handlers:
            yield
            return
        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM)

        def _flip(_signum: int, _frame: object) -> None:
            self._signal_received = True

        try:
            signal.signal(signal.SIGINT, _flip)
            signal.signal(signal.SIGTERM, _flip)
            yield
        finally:
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)
            self._signal_received = False

    # --------------------------------------------------------- terminations

    def _finish_needs_human(self, epic: EpicState, child_issue: int) -> int:
        epic["status"] = "HALTED"
        self.state_store.save_epic(epic)
        child = self.state_store.load_child(epic["epic_issue_number"], child_issue)
        body = render_needs_human(
            epic_issue=epic["epic_issue_number"],
            child_issue=child_issue,
            state_path=self._repo_relative_path(
                self.state_store.child_path(epic["epic_issue_number"], child_issue)
            ),
            failed_state=child["status"],
            last_verdict=child["last_verdict"],
            detail=child["needs_human_reason"] or "(no detail)",
        )
        self.escalator.comment(epic["epic_issue_number"], body)
        return EXIT_NEEDS_HUMAN

    def _repo_relative_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.repo_root))
        except ValueError:
            return str(path)

    def _finish_halted(self, epic: EpicState, reason: str) -> int:
        epic["status"] = "HALTED"
        if epic["epic_issue_number"]:
            self.state_store.save_epic(epic)
        self.escalator.comment(
            epic["epic_issue_number"], render_halted(epic["epic_issue_number"], reason)
        )
        return EXIT_HALTED

    def _finish_done(self, epic: EpicState) -> int:
        epic["status"] = "DONE"
        self.state_store.save_epic(epic)
        self.escalator.comment(
            epic["epic_issue_number"],
            render_epic_done(
                epic["epic_issue_number"],
                epic["children_done"],
                epic["children_skipped"],
            ),
        )
        return EXIT_OK


# ============================================================
# State handlers
# ============================================================


def _handle_triage(runner: Runner, epic: EpicState, child: ChildState) -> None:
    body = runner.git_ops.fetch_issue_body(child["issue_number"])
    runner.state_store.write_artifact(
        epic["epic_issue_number"], child["issue_number"], "issue.txt", body
    )
    result = runner.subagent.invoke("/triage-issue", body, PER_STAGE_BUDGET_USD)
    runner.record_subagent(epic, child, "/triage-issue", result, "triage.md")
    if result.exit_code != 0:
        _retry_or_escalate(
            runner, epic, child,
            key="triage", limit=TRIAGE_MAX_ATTEMPTS,
            reason="triage exit_code != 0",
        )
        return
    try:
        readiness = parse_triage(result.raw_stdout)
    except ParseError as exc:
        child["needs_human_reason"] = f"triage parse failed: {exc}"
        runner.transition(epic, child, "NEEDS_HUMAN")
        return
    if readiness == "ready":
        runner.transition(epic, child, "PACKETIZE")
    elif readiness == "do-not-run":
        runner.transition(epic, child, "SKIPPED")
    else:
        child["needs_human_reason"] = "triage readiness=needs-confirmation"
        runner.transition(epic, child, "NEEDS_HUMAN")


def _handle_packetize(runner: Runner, epic: EpicState, child: ChildState) -> None:
    issue_path = runner.state_store.child_dir(
        epic["epic_issue_number"], child["issue_number"]
    ) / "issue.txt"
    body = issue_path.read_text(encoding="utf-8") if issue_path.exists() else ""
    result = runner.subagent.invoke("/make-execution-packet", body, PER_STAGE_BUDGET_USD)
    runner.record_subagent(epic, child, "/make-execution-packet", result, "packet.yaml")
    if result.exit_code != 0:
        _retry_or_escalate(
            runner, epic, child,
            key="packetize", limit=PACKETIZE_MAX_ATTEMPTS,
            reason="packetize exit_code != 0",
        )
        return
    try:
        parse_packet(result.raw_stdout)
    except ParseError as exc:
        child["needs_human_reason"] = f"packet parse failed: {exc}"
        runner.transition(epic, child, "NEEDS_HUMAN")
        return
    runner.transition(epic, child, "PLAN")


def _handle_plan(runner: Runner, epic: EpicState, child: ChildState) -> None:
    packet_path = runner.state_store.child_dir(
        epic["epic_issue_number"], child["issue_number"]
    ) / "packet.yaml"
    packet = packet_path.read_text(encoding="utf-8") if packet_path.exists() else ""
    result = runner.subagent.invoke("/spec-architect", packet, PER_STAGE_BUDGET_USD)
    runner.record_subagent(epic, child, "/spec-architect", result, "plan.md")
    if result.exit_code != 0:
        _retry_or_escalate(
            runner, epic, child,
            key="plan", limit=PLAN_MAX_ATTEMPTS,
            reason="plan exit_code != 0",
        )
        return
    try:
        rec = parse_plan(result.raw_stdout)
    except ParseError as exc:
        _retry_or_escalate(
            runner, epic, child,
            key="plan", limit=PLAN_MAX_ATTEMPTS,
            reason=f"plan parse failed: {exc}",
        )
        return
    if rec == "proceed":
        runner.transition(epic, child, "IMPLEMENT")
    else:
        child["needs_human_reason"] = f"plan recommendation={rec}"
        runner.transition(epic, child, "NEEDS_HUMAN")


def _handle_implement(runner: Runner, epic: EpicState, child: ChildState) -> None:
    packet_path = runner.state_store.child_dir(
        epic["epic_issue_number"], child["issue_number"]
    ) / "packet.yaml"
    packet = packet_path.read_text(encoding="utf-8") if packet_path.exists() else ""
    result = runner.subagent.invoke("/run-dev-loop", packet, PER_STAGE_BUDGET_USD)
    runner.record_subagent(epic, child, "/run-dev-loop", result, "dev_loop.md")
    if result.exit_code != 0:
        _retry_or_escalate(
            runner, epic, child,
            key="implement", limit=IMPLEMENT_MAX_ATTEMPTS,
            reason="dev-loop exit_code != 0",
        )
        return
    try:
        outcome = parse_dev_loop(result.raw_stdout)
    except ParseError as exc:
        child["needs_human_reason"] = f"dev-loop parse failed: {exc}"
        runner.transition(epic, child, "NEEDS_HUMAN")
        return
    child["last_verdict"] = outcome.verdict
    runner.state_store.save_child(epic["epic_issue_number"], child)
    if outcome.verdict == "safe to merge":
        runner.transition(epic, child, "VERIFY_PR")
    elif outcome.verdict == "fix before merge":
        _retry_or_escalate(
            runner, epic, child,
            key="implement", limit=IMPLEMENT_MAX_ATTEMPTS,
            reason="verdict=fix before merge",
        )
    else:
        child["needs_human_reason"] = f"verdict={outcome.verdict}"
        runner.transition(epic, child, "NEEDS_HUMAN")


def _handle_verify_pr(runner: Runner, epic: EpicState, child: ChildState) -> None:
    url = runner.git_ops.find_pr_url(child["branch"], epic["epic_branch"])
    if url is None:
        if child["retry"]["verify_pr"] >= VERIFY_PR_MAX_ATTEMPTS:
            child["needs_human_reason"] = "PR not found after retries"
            runner.transition(epic, child, "NEEDS_HUMAN")
            return
        child["retry"]["verify_pr"] += 1
        runner.state_store.save_child(epic["epic_issue_number"], child)
        return
    child["pr_url"] = url
    # /pr-creation hard-codes `--base main`; retarget to the epic branch so the
    # epic accumulates child PRs as designed. Soft-fail: a failed retarget logs
    # but doesn't escalate (the PR still exists, just on the wrong base).
    retargeted = runner.git_ops.retarget_pr(url, epic["epic_branch"])
    runner._log(
        epic["epic_issue_number"],
        {
            "event": "pr_retarget",
            "child": child["issue_number"],
            "pr_url": url,
            "new_base": epic["epic_branch"],
            "ok": retargeted,
        },
    )
    runner.transition(epic, child, "DONE")


_HANDLERS: dict[ChildStatus, Handler] = {
    "TRIAGE": _handle_triage,
    "PACKETIZE": _handle_packetize,
    "PLAN": _handle_plan,
    "IMPLEMENT": _handle_implement,
    "VERIFY_PR": _handle_verify_pr,
}


def _retry_or_escalate(
    runner: Runner,
    epic: EpicState,
    child: ChildState,
    *,
    key: RetryKey,
    limit: int,
    reason: str,
) -> None:
    """Increment the retry counter for `key`. If the limit is reached, escalate."""
    current = get_retry(child["retry"], key)
    if current >= limit:
        child["needs_human_reason"] = f"{reason} (retry exhausted: {key}={current}/{limit})"
        runner.transition(epic, child, "NEEDS_HUMAN")
        return
    set_retry(child["retry"], key, current + 1)
    runner.state_store.save_child(epic["epic_issue_number"], child)


def _placeholder_epic(epic_issue: int) -> EpicState:
    placeholder: EpicState = {
        "epic_issue_number": epic_issue,
        "epic_branch": "",
        "status": "HALTED",
        "children_queue": [],
        "children_done": [],
        "children_skipped": [],
        "children_failed": [],
        "current_child": None,
        "started_at": "",
        "updated_at": "",
        "cost_usd": 0.0,
        "diff_lines": 0,
        "schema_version": 1,
    }
    return placeholder
