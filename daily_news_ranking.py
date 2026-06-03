"""Goal-conditioned ranking and digest slot planning (KAZ-202 / KAZ-204)."""

from __future__ import annotations

import random
from typing import Any, Sequence

from goals.subjects import DISPLAY_NAMES, SUBJECT_ALLOWLIST
from ranking import blend_centroids, cosine_similarity

NOVELTY_SIM_THRESHOLD = 0.28


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


def score_candidates_multi_project(
    candidates: list[dict],
    vectors: list[list[float] | None],
    project_centroids: dict[str, list[float]],
    *,
    ranking_weight: float,
    sim_base: float,
    jitter_base: float,
) -> None:
    """Assign ``target_project``, ``project_sim``, and ranking ``score`` per candidate."""
    weight = max(0.0, min(1.0, ranking_weight))
    for candidate, vec in zip(candidates, vectors, strict=False):
        if vec is None or not project_centroids:
            candidate["project_sim"] = 0.0
            candidate["target_project"] = None
            candidate["digest_lane"] = "novelty"
            candidate["sim"] = 0.0
            candidate["score"] = random.random()
            continue

        best_slug: str | None = None
        best_sim = 0.0
        for slug, centroid in project_centroids.items():
            sim = cosine_similarity(vec, centroid)
            if sim > best_sim:
                best_sim = sim
                best_slug = slug

        candidate["project_sim"] = best_sim
        candidate["target_project"] = best_slug
        if best_sim < NOVELTY_SIM_THRESHOLD:
            candidate["digest_lane"] = "novelty"
            candidate["sim"] = best_sim
        else:
            candidate["digest_lane"] = "project"
            candidate["sim"] = best_sim

        candidate["score"] = candidate["sim"] * sim_base * weight + random.random() * (
            1.0 - (sim_base - jitter_base) * weight
        )


def build_digest_plan_v2(
    ranked: list[dict],
    *,
    subject_slugs: tuple[str, ...] = SUBJECT_ALLOWLIST,
    max_stories: int,
    challenge_min: int = 1,
    challenge_max: int = 1,
    novelty_max: int = 1,
) -> tuple[list[dict], list[dict]]:
    """Per-project top story first, then novelty/challenge/fill. Returns plan + inbox overflow."""
    if not ranked or max_stories <= 0:
        return [], []

    picked_ids: set[str] = set()
    plan: list[dict] = []
    inbox_overflow: list[dict] = []

    for slug in subject_slugs:
        if len(plan) >= max_stories:
            break
        label = DISPLAY_NAMES.get(slug, slug)
        best: dict | None = None
        for candidate in ranked:
            if candidate["content_id"] in picked_ids:
                continue
            if candidate.get("target_project") != slug:
                continue
            if best is None or float(candidate.get("project_sim", 0)) > float(
                best.get("project_sim", 0)
            ):
                best = candidate
        if best is None:
            continue
        plan.append(
            {
                **best,
                "digest_slot": "project",
                "display_category": f"→ {label}",
            }
        )
        picked_ids.add(best["content_id"])

    novelty_pool = [
        c
        for c in ranked
        if c.get("digest_lane") == "novelty" and c["content_id"] not in picked_ids
    ]
    novelty_pool.sort(key=lambda c: float(c.get("score", 0)), reverse=True)
    if novelty_pool:
        pick = novelty_pool[0]
        if len(plan) < max_stories:
            plan.append(
                {**pick, "digest_slot": "novelty", "display_category": "Idea"}
            )
            picked_ids.add(pick["content_id"])
        elif novelty_max > 0:
            inbox_overflow.append(pick)

    n_challenge = 0
    if len(plan) < max_stories and challenge_min > 0:
        n_challenge = min(challenge_max, challenge_min, max_stories - len(plan))

    by_sim_asc = sorted(
        [c for c in ranked if c["content_id"] not in picked_ids],
        key=lambda c: float(c.get("project_sim", c.get("sim", 0))),
    )
    for pick in by_sim_asc[:n_challenge]:
        if len(plan) >= max_stories:
            break
        plan.append({**pick, "digest_slot": "challenge", "display_category": "Challenge"})
        picked_ids.add(pick["content_id"])

    for candidate in ranked:
        if len(plan) >= max_stories:
            break
        if candidate["content_id"] in picked_ids:
            continue
        plan.append({**candidate, "digest_slot": "fill"})
        picked_ids.add(candidate["content_id"])

    return plan, inbox_overflow
