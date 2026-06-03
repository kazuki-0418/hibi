"""Tests for goals.loader active-project conventions (KAZ-202)."""

import os
from pathlib import Path

import pytest

from goals import loader as goals_loader


def test_load_goal_focus_extracts_active_sections(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    project = vault / "10_projects" / "hibi"
    project.mkdir(parents=True)
    note = project / "status.md"
    note.write_text(
        "---\nstatus: active\n---\n"
        "## Goal\nBuild the digest pipeline.\n\n"
        "## Notes\nPrivate diary.\n",
        encoding="utf-8",
    )
    monkeypatch.delenv(goals_loader.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(goals_loader.OPTIONAL_ENV, raising=False)
    monkeypatch.setenv(goals_loader.VAULT_ROOT_ENV, str(vault))

    focus = goals_loader.load_goal_focus()
    assert "hibi" in focus.project_slugs
    assert "Build the digest pipeline" in focus.text
    assert "Private diary" not in focus.text


def test_abandoned_paths_skipped(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    archived = vault / "10_projects" / "old" / "archive" / "x.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("---\nstatus: active\n---\n## Goal\nhidden\n", encoding="utf-8")
    monkeypatch.setenv(goals_loader.VAULT_ROOT_ENV, str(vault))
    monkeypatch.delenv(goals_loader.OVERRIDE_ENV, raising=False)

    focus = goals_loader.load_goal_focus()
    assert focus.text == ""
    assert focus.project_slugs == ()


def test_override_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(goals_loader.OVERRIDE_ENV, "Demo goal focus")
    focus = goals_loader.load_goal_focus()
    assert focus.text == "Demo goal focus"
    assert focus.project_slugs == ("override",)


def test_missing_vault_optional_returns_empty(monkeypatch) -> None:
    monkeypatch.delenv(goals_loader.VAULT_ROOT_ENV, raising=False)
    monkeypatch.setenv(goals_loader.OPTIONAL_ENV, "1")
    focus = goals_loader.load_goal_focus()
    assert focus.text == ""
