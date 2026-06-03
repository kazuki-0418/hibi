"""Goal-conditioned ranking and digest slot planning (KAZ-202)."""

from __future__ import annotations

import random
from typing import Any, Sequence

from ranking import blend_centroids, cosine_similarity


def resolve_ranking_centroid(
    click_centroid: Any,
    goal_centroid: Sequence[float] | None,
    click_count: int,
    *,
    cold_start_clicks: int,
    full_weight_clicks: int,
) -> Any:
    """Pick centroid for ranking: goal when clicks are sparse, blend when both exist."""
    if goal_centroid is None and click_centroid is None:
        return None
    if goal_centroid is None:
        return click_centroid
    if click_centroid is None or click_count < cold_start_clicks:
        return goal_centroid
    click_weight = min(1.0, click_count / full_weight_clicks)
    return blend_centroids(goal_centroid, click_centroid, click_weight)


def score_candidates(
    candidates: list[dict],
    vectors: list[list[float] | None],
    centroid: Sequence[float],
    *,
    ranking_weight: float,
    sim_base: float,
    jitter_base: float,
) -> None:
    """Write ``sim`` and ``score`` on each candidate (in place)."""
    weight = max(0.0, min(1.0, ranking_weight))
    for candidate, vec in zip(candidates, vectors, strict=False):
        if vec is None:
            candidate["sim"] = 0.0
        else:
            candidate["sim"] = cosine_similarity(vec, centroid)
        candidate["score"] = candidate["sim"] * sim_base * weight + random.random() * (
            1.0 - (sim_base - jitter_base) * weight
        )


def build_digest_plan(
    ranked: list[dict],
    max_stories: int,
    *,
    challenge_min: int = 1,
    challenge_max: int = 2,
) -> list[dict]:
    """Build up to ``max_stories`` items with ``digest_slot`` goal or challenge."""
    if not ranked or max_stories <= 0:
        return []

    n = min(max_stories, len(ranked))
    n_challenge = 0
    if n >= 2 and challenge_min > 0:
        n_challenge = min(challenge_max, challenge_min, n - 1)

    by_sim_asc = sorted(ranked, key=lambda c: float(c.get("sim", 0.0)))
    challenge_picks = by_sim_asc[:n_challenge]
    challenge_ids = {c["content_id"] for c in challenge_picks}
    n_goal = n - len(challenge_picks)

    plan: list[dict] = []
    for candidate in ranked:
        if candidate["content_id"] in challenge_ids:
            continue
        if len(plan) >= n_goal:
            break
        plan.append({**candidate, "digest_slot": "goal"})

    for pick in challenge_picks:
        plan.append({**pick, "digest_slot": "challenge"})
    return plan
