from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ._subprocess import run
from .git_ops import GitOpsError


class Escalator(Protocol):
    def comment(self, issue: int, body: str) -> None: ...


@dataclass
class DummyEscalator:
    """Records every comment that would have been posted."""

    posted: list[tuple[int, str]] = field(default_factory=list)

    def comment(self, issue: int, body: str) -> None:
        self.posted.append((issue, body))


@dataclass
class RealEscalator:
    """Phase 3 implementation. Posts via `gh issue comment`."""

    repo_root: Path
    gh_bin: str = "gh"

    def comment(self, issue: int, body: str) -> None:
        # Pass body via stdin (`-F -`) to avoid shell quoting issues with
        # multi-line markdown content.
        result = run(
            [self.gh_bin, "issue", "comment", str(issue), "-F", "-"],
            stdin=body,
            cwd=str(self.repo_root),
        )
        if result.exit_code != 0:
            raise GitOpsError(
                f"gh issue comment {issue} failed (exit={result.exit_code}): "
                f"{result.stderr.strip()}"
            )


# ============================================================
# Body renderers (shared by Dummy and Real)
# ============================================================


def render_needs_human(
    epic_issue: int,
    child_issue: int,
    state_path: str,
    failed_state: str,
    last_verdict: str | None,
    detail: str,
) -> str:
    return (
        f"Manager halted on child #{child_issue}\n"
        f"\n"
        f"- epic: #{epic_issue}\n"
        f"- failed_state: {failed_state}\n"
        f"- last_verdict: {last_verdict or 'n/a'}\n"
        f"- state_file: `{state_path}`\n"
        f"\n"
        f"## Detail\n"
        f"{detail.strip()}\n"
        f"\n"
        f"Resume with `python -m manager resume {epic_issue}` after fixing.\n"
    )


def render_epic_done(epic_issue: int, done: list[int], skipped: list[int]) -> str:
    parts = [f"Manager finished epic #{epic_issue}.", ""]
    parts.append(f"- done: {done or 'none'}")
    parts.append(f"- skipped: {skipped or 'none'}")
    return "\n".join(parts) + "\n"


def render_halted(epic_issue: int, reason: str) -> str:
    return f"Manager halted epic #{epic_issue}: {reason}\n"
