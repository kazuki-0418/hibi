"""Tests for scripts/verify_vault_goal_paths.py (KAZ-206)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_verify_vault_goal_paths_ok(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    mono = vault / "10_projects" / "monogatari"
    mono.mkdir(parents=True)
    (mono / "decisions.md").write_text("x", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))

    proc = subprocess.run(
        [sys.executable, "scripts/verify_vault_goal_paths.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "OK" in proc.stdout


def test_verify_vault_goal_paths_missing_root(monkeypatch) -> None:
    monkeypatch.delenv("OBSIDIAN_VAULT_ROOT", raising=False)
    proc = subprocess.run(
        [sys.executable, "scripts/verify_vault_goal_paths.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
