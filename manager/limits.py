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

# EPIC_BUDGET_USD is a runaway-protection cap, NOT a billing limit. The
# `total_cost_usd` value reported by `claude -p` is the equivalent API price
# computed from token usage; on Claude Max plan (the default auth path —
# see `manager/subagent.py::RealSubagent` and `.claude/rules/manager-agent.md`)
# none of it shows up on a card. The cap exists only to stop loops, stuck
# children, or unexpected fanouts from burning Max plan quota indefinitely.
#
# Sizing: typical child runs $1–$3, heavy children with retries can hit
# $5–$7. 5 heavy children per epic ≈ $35 natural max. Set the cap above
# that so normal completion never trips it; reserve the trip for true
# runaways (infinite retry loops, parser bugs, child fanout). $80 also
# stays inside one 5-hour Max plan window (~$140 on 5x, ~$200+ on 20x)
# so a runaway gets stopped before exhausting the window.
EPIC_BUDGET_USD: float = 80.0

# PER_STAGE_BUDGET_USD is passed to `claude -p --max-budget-usd` per subagent
# call as a soft cap. If the call exceeds it, claude returns
# `subtype=error_max_budget_usd, is_error=true` and exits non-zero — the
# work in progress is aborted mid-turn.
#
# At $1 the heaviest stage (`/run-dev-loop`) couldn't complete: a real
# IMPLEMENT involves reading project context + design-system + writing
# code + invoking implementation-reviewer/test-qa internally, easily
# 30–50 turns. Empirically a single /run-dev-loop call hit $1 after only
# 21 turns and bailed before finishing.
#
# At $10 cheap stages (TRIAGE ~$0.2–$0.3, PACKETIZE ~$0.3) stay nowhere
# near the cap; PLAN ~$0.5–$1.5 has comfortable headroom; IMPLEMENT can
# burn its full ~$5–$8 budget without truncation. The EPIC_BUDGET_USD
# cap above is still the real safety net against runaways.
PER_STAGE_BUDGET_USD: float = 10.0

MAX_DIFF_LINES_PER_CHILD: int = 1500

NETWORK_BACKOFF_SECONDS: tuple[int, ...] = (5, 15, 45)

SCHEMA_VERSION: int = 1

EXIT_OK: int = 0
EXIT_NEEDS_HUMAN: int = 2
EXIT_HALTED: int = 3
EXIT_LOCK_TAKEN: int = 4
