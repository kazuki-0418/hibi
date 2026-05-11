from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .limits import EPIC_BUDGET_USD, MAX_DIFF_LINES_PER_CHILD


@dataclass(frozen=True)
class Checkpoint:
    """A precondition checked at every state transition.

    `tripped == True` means: stop the state machine. `reason` is the human-readable
    explanation written to the log + Issue comment.
    """

    tripped: bool
    reason: str
    fatal: bool  # if True -> HALTED (immediate); if False -> NEEDS_HUMAN at child boundary


def kill_switch(stop_root: Path) -> Checkpoint:
    if (stop_root / ".claude" / "STOP_NOW").exists():
        return Checkpoint(tripped=True, reason="STOP_NOW marker present", fatal=True)
    if (stop_root / ".claude" / "STOP").exists():
        return Checkpoint(tripped=True, reason="STOP marker present", fatal=True)
    return Checkpoint(tripped=False, reason="", fatal=False)


def cost_check(epic_cost_usd: float) -> Checkpoint:
    if epic_cost_usd >= EPIC_BUDGET_USD:
        return Checkpoint(
            tripped=True,
            reason=f"epic cost {epic_cost_usd:.2f} USD reached EPIC_BUDGET_USD={EPIC_BUDGET_USD}",
            fatal=False,
        )
    return Checkpoint(tripped=False, reason="", fatal=False)


def diff_check(child_diff_lines: int) -> Checkpoint:
    if child_diff_lines >= MAX_DIFF_LINES_PER_CHILD:
        return Checkpoint(
            tripped=True,
            reason=(
                f"child diff {child_diff_lines} lines >= MAX_DIFF_LINES_PER_CHILD="
                f"{MAX_DIFF_LINES_PER_CHILD}"
            ),
            fatal=False,
        )
    return Checkpoint(tripped=False, reason="", fatal=False)


def deps_check(requirements_changed: bool) -> Checkpoint:
    if requirements_changed:
        return Checkpoint(
            tripped=True,
            reason="requirements.txt changed — new dependency requires human review",
            fatal=False,
        )
    return Checkpoint(tripped=False, reason="", fatal=False)
