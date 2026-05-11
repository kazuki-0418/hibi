"""State machine definition.

Pure data: every transition condition is encoded here as a name. The runner is
responsible for *evaluating* the conditions; this module is responsible only for
declaring which transitions are *legal*. That split is what lets us assert in
tests that no illegal transition exists in the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import ChildStatus

TERMINAL_STATES: frozenset[ChildStatus] = frozenset({"DONE", "SKIPPED", "NEEDS_HUMAN"})


@dataclass(frozen=True)
class Transition:
    src: ChildStatus
    dst: ChildStatus
    condition: str


LEGAL_TRANSITIONS: tuple[Transition, ...] = (
    Transition("INIT", "TRIAGE", "branch created"),
    Transition("INIT", "NEEDS_HUMAN", "git ops failed"),

    Transition("TRIAGE", "PACKETIZE", "readiness=ready"),
    Transition("TRIAGE", "NEEDS_HUMAN", "readiness=needs-confirmation"),
    Transition("TRIAGE", "SKIPPED", "readiness=do-not-run"),
    Transition("TRIAGE", "TRIAGE", "retry within budget"),
    Transition("TRIAGE", "NEEDS_HUMAN", "triage retry exhausted"),

    Transition("PACKETIZE", "PLAN", "packet parsed"),
    Transition("PACKETIZE", "NEEDS_HUMAN", "packet parse failed"),

    Transition("PLAN", "IMPLEMENT", "recommendation=proceed"),
    Transition("PLAN", "NEEDS_HUMAN", "recommendation=confirm first"),
    Transition("PLAN", "PLAN", "plan retry within budget"),
    Transition("PLAN", "NEEDS_HUMAN", "plan retry exhausted"),

    Transition("IMPLEMENT", "VERIFY_PR", "verdict=safe to merge"),
    Transition("IMPLEMENT", "IMPLEMENT", "verdict=fix before merge, retry"),
    Transition("IMPLEMENT", "NEEDS_HUMAN", "verdict=confirm before merge"),
    Transition("IMPLEMENT", "NEEDS_HUMAN", "implement retry exhausted"),

    Transition("VERIFY_PR", "DONE", "PR found"),
    Transition("VERIFY_PR", "VERIFY_PR", "PR not found, retry"),
    Transition("VERIFY_PR", "NEEDS_HUMAN", "verify_pr retry exhausted"),
)


def is_legal(src: ChildStatus, dst: ChildStatus) -> bool:
    return any(t.src == src and t.dst == dst for t in LEGAL_TRANSITIONS)
