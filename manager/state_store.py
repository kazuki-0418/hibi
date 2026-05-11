from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .limits import SCHEMA_VERSION
from .types import ChildState, EpicState, RetryCounters


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    bak = path.with_suffix(path.suffix + ".bak")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if path.exists():
        os.replace(path, bak)
    os.replace(tmp, path)


def _safe_read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        bak = path.with_suffix(path.suffix + ".bak")
        if bak.exists():
            return json.loads(bak.read_text(encoding="utf-8"))
        raise


class LockTaken(Exception):
    """Another Manager process holds the epic lock."""


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def epic_dir(self, epic_issue: int) -> Path:
        return self.root / f"epic-{epic_issue}"

    def epic_path(self, epic_issue: int) -> Path:
        return self.epic_dir(epic_issue) / "epic.json"

    def child_dir(self, epic_issue: int, child_issue: int) -> Path:
        return self.epic_dir(epic_issue) / "children" / f"child-{child_issue}"

    def child_path(self, epic_issue: int, child_issue: int) -> Path:
        return self.child_dir(epic_issue, child_issue) / "state.json"

    def lock_path(self, epic_issue: int) -> Path:
        return self.epic_dir(epic_issue) / "lock"

    def log_path(self, epic_issue: int) -> Path:
        return self.epic_dir(epic_issue) / "log.jsonl"

    def init_epic(
        self,
        epic_issue: int,
        epic_branch: str,
        children: list[int],
    ) -> EpicState:
        ts = now_iso()
        state: EpicState = {
            "epic_issue_number": epic_issue,
            "epic_branch": epic_branch,
            "status": "RUNNING",
            "children_queue": list(children),
            "children_done": [],
            "children_skipped": [],
            "children_failed": [],
            "current_child": None,
            "started_at": ts,
            "updated_at": ts,
            "cost_usd": 0.0,
            "diff_lines": 0,
            "schema_version": SCHEMA_VERSION,
        }
        self.save_epic(state)
        return state

    def load_epic(self, epic_issue: int) -> EpicState:
        return _coerce_epic(_safe_read(self.epic_path(epic_issue)))

    def save_epic(self, state: EpicState) -> None:
        state["updated_at"] = now_iso()
        _atomic_write(self.epic_path(state["epic_issue_number"]), dict(state))

    def init_child(self, epic_issue: int, child_issue: int, branch: str) -> ChildState:
        ts = now_iso()
        retry: RetryCounters = {
            "plan": 0,
            "implement": 0,
            "triage": 0,
            "packetize": 0,
            "verify_pr": 0,
        }
        state: ChildState = {
            "issue_number": child_issue,
            "branch": branch,
            "status": "INIT",
            "started_at": ts,
            "updated_at": ts,
            "retry": retry,
            "last_verdict": None,
            "pr_url": None,
            "needs_human_reason": None,
            "artifacts": {},
            "cost_usd": 0.0,
        }
        self.save_child(epic_issue, state)
        return state

    def load_child(self, epic_issue: int, child_issue: int) -> ChildState:
        return _coerce_child(_safe_read(self.child_path(epic_issue, child_issue)))

    def save_child(self, epic_issue: int, state: ChildState) -> None:
        state["updated_at"] = now_iso()
        _atomic_write(self.child_path(epic_issue, state["issue_number"]), dict(state))

    def write_artifact(
        self,
        epic_issue: int,
        child_issue: int,
        name: str,
        content: str,
    ) -> Path:
        path = self.child_dir(epic_issue, child_issue) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def append_log(self, epic_issue: int, event: dict[str, Any]) -> None:
        record = dict(event)
        record["ts"] = now_iso()
        path = self.log_path(epic_issue)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, sort_keys=True) + "\n")

    @contextmanager
    def epic_lock(self, epic_issue: int) -> Iterator[None]:
        path = self.lock_path(epic_issue)
        path.parent.mkdir(parents=True, exist_ok=True)
        fp = path.open("a+")
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            fp.close()
            raise LockTaken(f"epic-{epic_issue} lock taken") from exc
        try:
            fp.seek(0)
            fp.truncate()
            fp.write(str(os.getpid()))
            fp.flush()
            yield
        finally:
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            finally:
                fp.close()


def _coerce_epic(raw: dict[str, Any]) -> EpicState:
    state: EpicState = {
        "epic_issue_number": int(raw["epic_issue_number"]),
        "epic_branch": str(raw["epic_branch"]),
        "status": raw["status"],
        "children_queue": [int(x) for x in raw.get("children_queue", [])],
        "children_done": [int(x) for x in raw.get("children_done", [])],
        "children_skipped": [int(x) for x in raw.get("children_skipped", [])],
        "children_failed": [int(x) for x in raw.get("children_failed", [])],
        "current_child": (int(raw["current_child"]) if raw.get("current_child") is not None else None),
        "started_at": str(raw["started_at"]),
        "updated_at": str(raw["updated_at"]),
        "cost_usd": float(raw.get("cost_usd", 0.0)),
        "diff_lines": int(raw.get("diff_lines", 0)),
        "schema_version": int(raw.get("schema_version", 1)),
    }
    return state


def _coerce_child(raw: dict[str, Any]) -> ChildState:
    retry_raw = raw.get("retry", {})
    retry: RetryCounters = {
        "plan": int(retry_raw.get("plan", 0)),
        "implement": int(retry_raw.get("implement", 0)),
        "triage": int(retry_raw.get("triage", 0)),
        "packetize": int(retry_raw.get("packetize", 0)),
        "verify_pr": int(retry_raw.get("verify_pr", 0)),
    }
    state: ChildState = {
        "issue_number": int(raw["issue_number"]),
        "branch": str(raw["branch"]),
        "status": raw["status"],
        "started_at": str(raw["started_at"]),
        "updated_at": str(raw["updated_at"]),
        "retry": retry,
        "last_verdict": raw.get("last_verdict"),
        "pr_url": raw.get("pr_url"),
        "needs_human_reason": raw.get("needs_human_reason"),
        "artifacts": dict(raw.get("artifacts", {})),
        "cost_usd": float(raw.get("cost_usd", 0.0)),
    }
    return state
