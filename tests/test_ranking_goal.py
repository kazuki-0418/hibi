"""Tests for goal/click centroid ranking helpers (KAZ-202)."""

from daily_news_ranking import build_digest_plan, resolve_ranking_centroid
from ranking import blend_centroids, cosine_similarity


def test_resolve_ranking_centroid_prefers_goal_on_cold_start() -> None:
    goal = [1.0, 0.0]
    click = [0.0, 1.0]
    out = resolve_ranking_centroid(
        click,
        goal,
        click_count=0,
        cold_start_clicks=5,
        full_weight_clicks=30,
    )
    assert out == goal


def test_blend_centroids_at_full_click_weight() -> None:
    goal = [1.0, 0.0]
    click = [0.0, 1.0]
    blended = blend_centroids(goal, click, 1.0)
    assert blended == [0.0, 1.0]


def test_cosine_similarity_zero_safe() -> None:
    assert cosine_similarity([], [1.0]) == 0.0


def test_build_digest_plan_includes_challenge_slot() -> None:
    ranked = [
        {"content_id": "a", "sim": 0.9, "title": "high"},
        {"content_id": "b", "sim": 0.1, "title": "low"},
        {"content_id": "c", "sim": 0.5, "title": "mid"},
    ]
    plan = build_digest_plan(ranked, max_stories=2, challenge_min=1, challenge_max=1)
    assert len(plan) == 2
    slots = {p["digest_slot"] for p in plan}
    assert slots == {"goal", "challenge"}
    challenge = next(p for p in plan if p["digest_slot"] == "challenge")
    assert challenge["content_id"] == "b"
