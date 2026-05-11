from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from manager.state_store import LockTaken, StateStore


def test_init_epic_round_trip(state_root: Path) -> None:
    store = StateStore(state_root)
    epic = store.init_epic(42, epic_branch="epic/42-foo", children=[1, 2, 3])
    assert epic["status"] == "RUNNING"
    assert epic["children_queue"] == [1, 2, 3]
    loaded = store.load_epic(42)
    assert loaded == epic


def test_init_child_round_trip(state_root: Path) -> None:
    store = StateStore(state_root)
    store.init_epic(42, "epic/42-foo", [1])
    child = store.init_child(42, 1, "epic/42-foo/child-1")
    assert child["status"] == "INIT"
    assert child["retry"]["plan"] == 0
    loaded = store.load_child(42, 1)
    assert loaded == child


def test_atomic_write_creates_bak_on_overwrite(state_root: Path) -> None:
    store = StateStore(state_root)
    store.init_epic(42, "epic/42-foo", [1])
    epic = store.load_epic(42)
    epic["status"] = "DONE"
    store.save_epic(epic)
    bak = store.epic_path(42).with_suffix(".json.bak")
    assert bak.exists()
    bak_data = json.loads(bak.read_text(encoding="utf-8"))
    assert bak_data["status"] == "RUNNING"


def test_safe_read_falls_back_to_bak(state_root: Path) -> None:
    store = StateStore(state_root)
    store.init_epic(42, "epic/42-foo", [1])
    epic = store.load_epic(42)
    epic["status"] = "DONE"
    store.save_epic(epic)
    # Corrupt the live file; .bak should still load.
    store.epic_path(42).write_text("{ broken json", encoding="utf-8")
    loaded = store.load_epic(42)
    assert loaded["status"] == "RUNNING"


def test_write_artifact(state_root: Path) -> None:
    store = StateStore(state_root)
    path = store.write_artifact(42, 1, "plan.md", "# hello")
    assert path.read_text(encoding="utf-8") == "# hello"
    assert path.parent.name == "child-1"


def test_append_log_jsonl(state_root: Path) -> None:
    store = StateStore(state_root)
    store.append_log(42, {"event": "a"})
    store.append_log(42, {"event": "b"})
    lines = store.log_path(42).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "a"


def test_epic_lock_blocks_concurrent_holder(state_root: Path) -> None:
    store = StateStore(state_root)
    with store.epic_lock(42):
        with pytest.raises(LockTaken):
            with store.epic_lock(42):
                pass


def test_lock_released_after_exit(state_root: Path) -> None:
    store = StateStore(state_root)
    with store.epic_lock(42):
        pass
    with store.epic_lock(42):
        pass  # second acquire must succeed
