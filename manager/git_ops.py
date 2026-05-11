from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ._subprocess import run


class GitOpsError(Exception):
    """Wraps a failed git/gh command. Manager treats this as NEEDS_HUMAN."""


class GitOps(Protocol):
    def create_epic_branch(self, epic_issue: int, slug: str) -> str: ...
    def create_child_branch(self, epic_branch: str, child_issue: int) -> str: ...
    def diff_lines(self, base_branch: str) -> int: ...
    def find_pr_url(self, head_branch: str, base_branch: str) -> str | None: ...
    def retarget_pr(self, pr_url: str, new_base: str) -> bool: ...
    def fetch_issue_body(self, issue: int) -> str: ...
    def list_child_issues(self, epic_issue: int) -> list[int]: ...


# ============================================================
# Dummy
# ============================================================


@dataclass
class DummyGitOps:
    """Records calls; returns canned values. Used by tests and `--dry-run`."""

    epic_branches: dict[int, str] = field(default_factory=dict)
    child_branches: dict[int, str] = field(default_factory=dict)
    diff_lines_value: int = 0
    pr_urls: dict[str, str] = field(default_factory=dict)
    issue_bodies: dict[int, str] = field(default_factory=dict)
    child_listing: dict[int, list[int]] = field(default_factory=dict)
    retargeted: dict[str, str] = field(default_factory=dict)
    failures: dict[str, GitOpsError] = field(default_factory=dict)

    def create_epic_branch(self, epic_issue: int, slug: str) -> str:
        self._maybe_fail("create_epic_branch")
        branch = f"epic/{epic_issue}-{slug}"
        self.epic_branches[epic_issue] = branch
        return branch

    def create_child_branch(self, epic_branch: str, child_issue: int) -> str:
        self._maybe_fail("create_child_branch")
        branch = child_branch_name(epic_branch, child_issue)
        self.child_branches[child_issue] = branch
        return branch

    def diff_lines(self, base_branch: str) -> int:
        return self.diff_lines_value

    def find_pr_url(self, head_branch: str, base_branch: str) -> str | None:
        return self.pr_urls.get(head_branch)

    def retarget_pr(self, pr_url: str, new_base: str) -> bool:
        self._maybe_fail("retarget_pr")
        self.retargeted[pr_url] = new_base
        return True

    def fetch_issue_body(self, issue: int) -> str:
        return self.issue_bodies.get(issue, "")

    def list_child_issues(self, epic_issue: int) -> list[int]:
        return list(self.child_listing.get(epic_issue, []))

    def _maybe_fail(self, op: str) -> None:
        if op in self.failures:
            raise self.failures[op]


# ============================================================
# Real
# ============================================================


_CHILDREN_HEADER_RE = re.compile(
    r"^##\s*(?:Children|子\s*Issue|子\s*issue|子課題|サブIssue)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_NEXT_HEADER_RE = re.compile(r"^##\s+\S", re.MULTILINE)
_CHILD_REF_RE = re.compile(r"#(\d+)")


def child_branch_name(epic_branch: str, child_issue: int) -> str:
    """Compose a child branch that won't collide with the epic branch's git ref.

    git refuses `refs/heads/X` and `refs/heads/X/Y` to coexist. So we must NOT
    reuse the epic branch as a path prefix for child branches. Append `-child-N`
    instead of `/child-N`.
    """
    return f"{epic_branch}-child-{child_issue}"


def parse_children_from_body(body: str) -> list[int]:
    """Extract child issue numbers from the `## Children` section of an epic body.

    Body format (convention):

        ## Children
        - #11 add fetcher A
        - #12 add fetcher B
        - #13 update mailer

    Returns issue numbers in the order they appear, deduplicated.
    """
    m = _CHILDREN_HEADER_RE.search(body)
    if not m:
        return []
    section_start = m.end()
    next_section = _NEXT_HEADER_RE.search(body, pos=section_start)
    section = body[section_start: next_section.start() if next_section else len(body)]
    seen: list[int] = []
    for ref in _CHILD_REF_RE.finditer(section):
        n = int(ref.group(1))
        if n not in seen:
            seen.append(n)
    return seen


@dataclass
class RealGitOps:
    """Phase 3 implementation. Calls `git` and `gh` via subprocess."""

    repo_root: Path
    base_branch: str = "main"
    git_bin: str = "git"
    gh_bin: str = "gh"

    def create_epic_branch(self, epic_issue: int, slug: str) -> str:
        branch = f"epic/{epic_issue}-{slug}"
        self._git("fetch", "origin", self.base_branch)
        # Idempotent: if the branch already exists, just check it out.
        existing = self._git("rev-parse", "--verify", "--quiet", branch, allow_fail=True)
        if existing.exit_code == 0:
            self._git("checkout", branch)
        else:
            self._git("checkout", "-b", branch, f"origin/{self.base_branch}")
        return branch

    def create_child_branch(self, epic_branch: str, child_issue: int) -> str:
        branch = child_branch_name(epic_branch, child_issue)
        existing = self._git("rev-parse", "--verify", "--quiet", branch, allow_fail=True)
        if existing.exit_code == 0:
            self._git("checkout", branch)
        else:
            self._git("checkout", epic_branch)
            self._git("checkout", "-b", branch)
        return branch

    def diff_lines(self, base_branch: str) -> int:
        result = self._git(
            "diff", "--numstat", f"{base_branch}...HEAD", allow_fail=True
        )
        if result.exit_code != 0:
            return 0
        total = 0
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            for raw in parts[:2]:
                if raw.isdigit():
                    total += int(raw)
        return total

    def find_pr_url(self, head_branch: str, base_branch: str) -> str | None:
        # Phase 3 limitation: existing /pr-creation hard-codes `--base main`, so
        # child PRs land on main rather than the epic branch. Until Phase 4
        # introduces a base-rewrite step, accept any base for the head branch.
        result = self._gh(
            "pr", "list",
            "--head", head_branch,
            "--state", "open",
            "--json", "url",
            "--jq", ".[0].url // empty",
            allow_fail=True,
        )
        if result.exit_code != 0:
            return None
        url = result.stdout.strip()
        return url or None

    def retarget_pr(self, pr_url: str, new_base: str) -> bool:
        """Move a PR to a different base branch via `gh pr edit <url> --base <branch>`.

        Returns True on success, False on failure (Manager treats False as a soft
        warning — the PR still exists on the original base, just not where we
        wanted). Does NOT raise so a transient failure doesn't escalate the
        whole child to NEEDS_HUMAN.
        """
        result = self._gh(
            "pr", "edit", pr_url, "--base", new_base, allow_fail=True,
        )
        return result.exit_code == 0

    def fetch_issue_body(self, issue: int) -> str:
        result = self._gh(
            "issue", "view", str(issue),
            "--json", "body",
            "--jq", ".body",
        )
        return result.stdout

    def list_child_issues(self, epic_issue: int) -> list[int]:
        body = self.fetch_issue_body(epic_issue)
        return parse_children_from_body(body)

    # --------------------------------------------------------- internals

    def _git(self, *args: str, allow_fail: bool = False):
        result = run([self.git_bin, *args], cwd=str(self.repo_root))
        if result.exit_code != 0 and not allow_fail:
            raise GitOpsError(
                f"git {' '.join(args)} failed (exit={result.exit_code}): {result.stderr.strip()}"
            )
        return result

    def _gh(self, *args: str, allow_fail: bool = False):
        result = run([self.gh_bin, *args], cwd=str(self.repo_root))
        if result.exit_code != 0 and not allow_fail:
            raise GitOpsError(
                f"gh {' '.join(args)} failed (exit={result.exit_code}): {result.stderr.strip()}"
            )
        return result
