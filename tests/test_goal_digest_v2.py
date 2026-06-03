"""Tests for goal-conditioned digest v2 (KAZ-204)."""

from __future__ import annotations

import json
from pathlib import Path

from daily_news_ranking import (
    NOVELTY_SIM_THRESHOLD,
    build_digest_plan_v2,
    score_candidates_multi_project,
)
from goals.centroids import embed_subject_centroids
from goals.subjects import load_subject_catalog
from goals.vault_io import write_novelty_inbox_item, write_raw_capture
from summarize_goal import build_summarize_prompt


def test_score_candidates_multi_project_assigns_best_slug() -> None:
    candidates = [
        {"content_id": "a", "title": "A", "description": ""},
        {"content_id": "b", "title": "B", "description": ""},
    ]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    centroids = {"monogatari": [1.0, 0.0], "roamlore": [0.0, 1.0]}
    score_candidates_multi_project(
        candidates,
        vectors,
        centroids,
        ranking_weight=1.0,
        sim_base=0.7,
        jitter_base=0.4,
    )
    assert candidates[0]["target_project"] == "monogatari"
    assert candidates[1]["target_project"] == "roamlore"
    assert candidates[0]["digest_lane"] == "project"
    assert candidates[1]["digest_lane"] == "project"


def test_build_digest_plan_v2_per_project_and_novelty() -> None:
    ranked = [
        {
            "content_id": "m1",
            "target_project": "monogatari",
            "project_sim": 0.9,
            "score": 1.0,
            "title": "mono high",
        },
        {
            "content_id": "r1",
            "target_project": "roamlore",
            "project_sim": 0.8,
            "score": 0.9,
            "title": "roam",
        },
        {
            "content_id": "n1",
            "digest_lane": "novelty",
            "project_sim": 0.1,
            "score": 0.5,
            "title": "novel",
        },
    ]
    plan, overflow = build_digest_plan_v2(ranked, max_stories=3, novelty_max=1)
    assert len(plan) == 3
    assert plan[0]["content_id"] == "m1"
    assert plan[0]["display_category"] == "→ Monogatari"
    assert plan[1]["content_id"] == "r1"
    assert plan[1]["display_category"] == "→ RoamLore"
    novelty = next(p for p in plan if p["digest_slot"] == "novelty")
    assert novelty["content_id"] == "n1"
    assert overflow == []


def test_build_digest_plan_v2_overflow_when_digest_full() -> None:
    ranked = [
        {
            "content_id": "m1",
            "target_project": "monogatari",
            "project_sim": 0.9,
            "score": 1.0,
            "title": "mono",
        },
        {
            "content_id": "n1",
            "digest_lane": "novelty",
            "project_sim": 0.1,
            "score": 0.5,
            "title": "novel",
        },
    ]
    plan, overflow = build_digest_plan_v2(ranked, max_stories=1, novelty_max=1)
    assert len(plan) == 1
    assert len(overflow) == 1
    assert overflow[0]["content_id"] == "n1"


def test_load_subject_catalog_from_fixture(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))
    monkeypatch.delenv("HIBI_GOALS_OPTIONAL", raising=False)
    proj = tmp_path / "10_projects" / "monogatari"
    proj.mkdir(parents=True)
    (proj / "decisions.md").write_text(
        "---\nstatus: active\n---\n## 決定\nShip v2 ranking.\n",
        encoding="utf-8",
    )

    catalog = load_subject_catalog()
    assert len(catalog.projects) == 1
    assert catalog.projects[0].slug == "monogatari"
    assert "Ship v2" in catalog.projects[0].conditioning_text


def test_subject_catalog_skips_inactive_conditioning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))
    monkeypatch.delenv("HIBI_GOALS_OPTIONAL", raising=False)
    proj = tmp_path / "10_projects" / "monogatari"
    proj.mkdir(parents=True)
    (proj / "decisions.md").write_text(
        "## 決定\nNo frontmatter.\n",
        encoding="utf-8",
    )
    (proj / "strategy.md").write_text(
        "---\nstatus: active\n---\n## 戦略\nActive strategy.\n",
        encoding="utf-8",
    )

    catalog = load_subject_catalog()
    text = catalog.projects[0].conditioning_text
    assert "Active strategy" in text
    assert "No frontmatter" not in text


def test_embed_subject_centroids_empty_catalog() -> None:
    from goals.subjects import SubjectCatalog

    class FakeClient:
        pass

    def fake_embed(_client, texts: list[str]) -> list[list[float]]:
        return [[float(i)] * 3 for i, _ in enumerate(texts)]

    assert (
        embed_subject_centroids(
            FakeClient(),
            SubjectCatalog(projects=()),
            embed_batch=fake_embed,
            embedding_model="test",
        )
        == {}
    )


def test_centroid_cache_hit(tmp_path: Path, monkeypatch) -> None:
    from goals.subjects import SubjectCatalog, SubjectProject

    class FakeClient:
        pass

    calls: list[int] = []

    def fake_embed(_client, texts: list[str]) -> list[list[float]]:
        calls.append(len(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]

    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("HIBI_GOAL_CACHE_DIR", str(cache_dir))
    project = SubjectProject(
        slug="monogatari",
        display_name="Monogatari",
        conditioning_text="focus text",
        file_count=1,
    )
    catalog = SubjectCatalog(projects=(project,))

    embed_subject_centroids(
        FakeClient(),
        catalog,
        embed_batch=fake_embed,
        embedding_model="text-embedding-3-small",
    )
    embed_subject_centroids(
        FakeClient(),
        catalog,
        embed_batch=fake_embed,
        embedding_model="text-embedding-3-small",
    )
    assert calls == [1]
    cache_file = cache_dir / "goal_centroid_cache.json"
    assert cache_file.is_file()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "monogatari" in data


def test_vault_io_capture_and_inbox(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))

    cap = write_raw_capture(
        title="Test Article",
        url="https://example.com/a",
        target_project="monogatari",
        summary="Summary line.",
        goal_note="→ Monogatari: note",
    )
    assert cap is not None
    assert "monogatari" in cap.read_text(encoding="utf-8")

    inbox1 = write_novelty_inbox_item(
        title="Novel idea",
        url="https://example.com/n",
        reason="low similarity",
    )
    assert inbox1 is not None
    inbox2 = write_novelty_inbox_item(
        title="Second novel",
        url="https://example.com/n2",
        reason="also low",
    )
    assert inbox2 is None


def test_summarize_prompt_includes_project_arrow() -> None:
    prompt = build_summarize_prompt(
        "Title",
        "Body",
        voice_rule="rule",
        content_char_limit=1000,
        goal_context="conditioning",
        target_project_label="Monogatari",
    )
    assert "→ Monogatari:" in prompt
    assert NOVELTY_SIM_THRESHOLD == 0.28
