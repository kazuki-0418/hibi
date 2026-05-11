"""Hard-coded operational limits for the Manager Agent.

These are intentionally constants (not env vars) so that loosening a guardrail
requires a code change + review.
"""

from __future__ import annotations

PLAN_MAX_ATTEMPTS: int = 2
IMPLEMENT_MAX_ATTEMPTS: int = 3
TRIAGE_MAX_ATTEMPTS: int = 1
PACKETIZE_MAX_ATTEMPTS: int = 1
VERIFY_PR_MAX_ATTEMPTS: int = 3

SUBAGENT_TIMEOUT_SECONDS: int = 900

EPIC_BUDGET_USD: float = 5.0
PER_STAGE_BUDGET_USD: float = 1.0

MAX_DIFF_LINES_PER_CHILD: int = 1500

NETWORK_BACKOFF_SECONDS: tuple[int, ...] = (5, 15, 45)

SCHEMA_VERSION: int = 1

EXIT_OK: int = 0
EXIT_NEEDS_HUMAN: int = 2
EXIT_HALTED: int = 3
EXIT_LOCK_TAKEN: int = 4
