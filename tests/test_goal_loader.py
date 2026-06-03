"""Tests for goals.loader active-project conventions (KAZ-202 / KAZ-204)."""

import os
import time
from pathlib import Path

from goals import loader as goals_loader


def test_load_goal_focus_extracts_active_sections(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    project = vault / "10_projects" / "monogatari"
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
    assert focus.project_slugs == ("monogatari",)
    assert "Build the digest pipeline" in focus.text
    assert "Private diary" not in focus.text


def test_allowlist_excludes_non_subject_projects(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    hibi = vault / "10_projects" / "hibi"
    hibi.mkdir(parents=True)
    (hibi / "status.md").write_text(
        "---\nstatus: active\n---\n## Goal\nHibi internal.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(goals_loader.VAULT_ROOT_ENV, str(vault))
    monkeypatch.delenv(goals_loader.OVERRIDE_ENV, raising=False)

    focus = goals_loader.load_goal_focus()
    assert focus.text == ""
    assert focus.project_slugs == ()


def test_strategy_heading_extracted(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    project = vault / "10_projects" / "roamlore"
    project.mkdir(parents=True)
    (project / "strategy.md").write_text(
        "---\nhibi-active: true\n---\n"
        "## 戦略\nLaunch in Q3.\n\n"
        "## Notes\nDiary noise.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(goals_loader.VAULT_ROOT_ENV, str(vault))
    monkeypatch.delenv(goals_loader.OVERRIDE_ENV, raising=False)

    focus = goals_loader.load_goal_focus()
    assert "Launch in Q3" in focus.text
    assert "Diary noise" not in focus.text


def test_recency_prefers_newer_note_before_cap(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    project = vault / "10_projects" / "monogatari"
    project.mkdir(parents=True)
    old = project / "decisions.md"
    new = project / "status.md"
    old.write_text(
        "---\nstatus: active\n---\n## 決定\nOLD_DECISION_TEXT.\n",
        encoding="utf-8",
    )
    new.write_text(
        "---\nstatus: active\n---\n## 現状\nNEW_STATUS_TEXT.\n",
        encoding="utf-8",
    )
    now = time.time()
    os.utime(old, (now - 86400 * 10, now - 86400 * 10))
    os.utime(new, (now, now))

    monkeypatch.setenv(goals_loader.VAULT_ROOT_ENV, str(vault))
    monkeypatch.delenv(goals_loader.OVERRIDE_ENV, raising=False)

    focus = goals_loader.load_goal_focus()
    assert focus.text.index("NEW_STATUS_TEXT") < focus.text.index("OLD_DECISION_TEXT")


def test_read_active_note_skips_without_frontmatter(tmp_path: Path, monkeypatch) -> None:
    note = tmp_path / "strategy.md"
    note.write_text("## 戦略\nNo frontmatter.\n", encoding="utf-8")
    monkeypatch.delenv(goals_loader.OPTIONAL_ENV, raising=False)

    assert goals_loader.read_active_note(note) == ""


def test_read_active_note_optional_allows_no_frontmatter(
    tmp_path: Path, monkeypatch
) -> None:
    note = tmp_path / "strategy.md"
    note.write_text("## strategy\nBody.\n", encoding="utf-8")
    monkeypatch.setenv(goals_loader.OPTIONAL_ENV, "1")

    assert "Body" in goals_loader.read_active_note(note)


def test_abandoned_paths_skipped(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    archived = vault / "10_projects" / "monogatari" / "archive" / "x.md"
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
