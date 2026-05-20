from __future__ import annotations

import re
from dataclasses import dataclass

from . import ParseError
from ..types import ReviewVerdict

_VERDICT_RE = re.compile(
    r"#\s*(?:Review\s+)?Verdict\s*\n+\s*-?\s*\*{0,2}`?(safe to merge|fix before merge|confirm before merge)`?\*{0,2}\b",
    re.IGNORECASE,
)
_PYTEST_RE = re.compile(
    r"##\s*Pytest Status\s*\n+\s*-?\s*(Pytest (?:Passed|Failed|Not Run))",
    re.IGNORECASE,
)
_DRYRUN_RE = re.compile(
    r"##\s*Dry-run Status\s*\n+\s*-?\s*(Dry-run (?:Passed|Failed|Not Run))",
    re.IGNORECASE,
)
_MIGR_RE = re.compile(
    r"##\s*Migration Apply Status\s*\n+\s*-?\s*(Migration (?:Applied|Pending|N/A))",
    re.IGNORECASE,
)
_BLOCKED_RE = re.compile(r"^#\s*Blocked\s*$", re.IGNORECASE | re.MULTILINE)
_PR_TITLE_RE = re.compile(r"##\s*Title\s*\n+\s*-?\s*(.+)$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class DevLoopOutcome:
    verdict: ReviewVerdict
    pytest_status: str | None
    dryrun_status: str | None
    migration_status: str | None
    pr_title: str | None
    blocked: bool


def parse_dev_loop(raw: str) -> DevLoopOutcome:
    if _BLOCKED_RE.search(raw):
        return DevLoopOutcome(
            verdict="confirm before merge",
            pytest_status=None,
            dryrun_status=None,
            migration_status=None,
            pr_title=None,
            blocked=True,
        )
    m = _VERDICT_RE.search(raw)
    if not m:
        raise ParseError("Review Verdict 行が見つからない")
    raw_verdict = m.group(1).lower()
    verdict: ReviewVerdict
    if raw_verdict == "safe to merge":
        verdict = "safe to merge"
    elif raw_verdict == "fix before merge":
        verdict = "fix before merge"
    else:
        verdict = "confirm before merge"

    return DevLoopOutcome(
        verdict=verdict,
        pytest_status=_first(_PYTEST_RE, raw),
        dryrun_status=_first(_DRYRUN_RE, raw),
        migration_status=_first(_MIGR_RE, raw),
        pr_title=_first(_PR_TITLE_RE, raw),
        blocked=False,
    )


def _first(pattern: re.Pattern[str], raw: str) -> str | None:
    m = pattern.search(raw)
    return m.group(1).strip() if m else None
