from __future__ import annotations

from typing import Literal, TypedDict

EpicStatus = Literal["INIT", "RUNNING", "DONE", "HALTED"]

ChildStatus = Literal[
    "INIT",
    "TRIAGE",
    "PACKETIZE",
    "PLAN",
    "IMPLEMENT",
    "VERIFY_PR",
    "DONE",
    "SKIPPED",
    "NEEDS_HUMAN",
]

RetryKey = Literal["plan", "implement", "triage", "packetize", "verify_pr"]

TerminalChildStatus = Literal["DONE", "SKIPPED", "NEEDS_HUMAN"]

TriageReadiness = Literal["ready", "needs-confirmation", "do-not-run"]
PlanRecommendation = Literal["proceed", "proceed with caution", "confirm first"]
ReviewVerdict = Literal["safe to merge", "fix before merge", "confirm before merge"]


class RetryCounters(TypedDict):
    plan: int
    implement: int
    triage: int
    packetize: int
    verify_pr: int


class ChildState(TypedDict):
    issue_number: int
    branch: str
    status: ChildStatus
    started_at: str
    updated_at: str
    retry: RetryCounters
    last_verdict: str | None
    pr_url: str | None
    needs_human_reason: str | None
    artifacts: dict[str, str]
    cost_usd: float


class EpicState(TypedDict):
    epic_issue_number: int
    epic_branch: str
    status: EpicStatus
    children_queue: list[int]
    children_done: list[int]
    children_skipped: list[int]
    children_failed: list[int]
    current_child: int | None
    started_at: str
    updated_at: str
    cost_usd: float
    diff_lines: int
    schema_version: int


def get_retry(counters: RetryCounters, key: RetryKey) -> int:
    if key == "plan":
        return counters["plan"]
    if key == "implement":
        return counters["implement"]
    if key == "triage":
        return counters["triage"]
    if key == "packetize":
        return counters["packetize"]
    return counters["verify_pr"]


def set_retry(counters: RetryCounters, key: RetryKey, value: int) -> None:
    if key == "plan":
        counters["plan"] = value
    elif key == "implement":
        counters["implement"] = value
    elif key == "triage":
        counters["triage"] = value
    elif key == "packetize":
        counters["packetize"] = value
    else:
        counters["verify_pr"] = value
