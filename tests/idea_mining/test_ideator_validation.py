"""Tests for `idea_mining.ideator.validate_candidate`.

Issue #138 acceptance:
- llm_moat_conditions が空 / null の候補は insert をスキップしログに残す。
- llm_moat_conditions は workflow / data / distribution / trust / network /
  physical / regulatory のいずれかのみ許可する。
- monetization は subscription / one-time / affiliate / freemium / b2b の
  いずれかに制約。
"""
from __future__ import annotations

from typing import Any

import pytest

from idea_mining.ideator import (
    ALLOWED_LLM_MOAT_CONDITIONS,
    ALLOWED_MONETIZATION,
    validate_candidate,
)


def _good_candidate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Spotline",
        "one_liner": "ローカル現場の B2B micro-SaaS bus mover",
        "target_user": "個人運送事業者",
        "monetization": "subscription",
        "llm_moat_conditions": ["workflow", "data"],
        "why_different": "コンセプト先行ではなく実運用ログから始まる",
        "estimated_mvp_hours": 40,
        "killer_use_case": "請求書を半自動で締める運用窓",
    }
    base.update(overrides)
    return base


def test_valid_candidate_passes() -> None:
    out, reason = validate_candidate(_good_candidate(), negative_names=[])

    assert reason is None
    assert out is not None
    assert out["name"] == "Spotline"
    assert out["monetization"] == "subscription"
    assert out["llm_moat_conditions"] == ["workflow", "data"]


# ----------------------------------------------------------------------
# llm_moat_conditions
# ----------------------------------------------------------------------


def test_rejects_empty_llm_moat_conditions() -> None:
    out, reason = validate_candidate(
        _good_candidate(llm_moat_conditions=[]), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "llm_moat_conditions" in reason


def test_rejects_missing_llm_moat_conditions_key() -> None:
    raw = _good_candidate()
    del raw["llm_moat_conditions"]

    out, reason = validate_candidate(raw, negative_names=[])

    assert out is None
    assert reason is not None
    assert "llm_moat_conditions" in reason


def test_rejects_null_llm_moat_conditions() -> None:
    out, reason = validate_candidate(
        _good_candidate(llm_moat_conditions=None), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "llm_moat_conditions" in reason


def test_rejects_invalid_llm_moat_condition_value() -> None:
    out, reason = validate_candidate(
        _good_candidate(llm_moat_conditions=["workflow", "vibes"]),
        negative_names=[],
    )

    assert out is None
    assert reason is not None
    assert "moat" in reason.lower()


def test_accepts_all_allowed_llm_moat_conditions() -> None:
    out, reason = validate_candidate(
        _good_candidate(llm_moat_conditions=sorted(ALLOWED_LLM_MOAT_CONDITIONS)),
        negative_names=[],
    )

    assert reason is None
    assert out is not None


def test_normalizes_llm_moat_condition_casing_and_whitespace() -> None:
    out, reason = validate_candidate(
        _good_candidate(llm_moat_conditions=[" Workflow ", "DATA"]),
        negative_names=[],
    )

    assert reason is None
    assert out is not None
    assert out["llm_moat_conditions"] == ["workflow", "data"]


def test_rejects_non_string_in_llm_moat_conditions() -> None:
    out, reason = validate_candidate(
        _good_candidate(llm_moat_conditions=["workflow", 7]),
        negative_names=[],
    )

    assert out is None
    assert reason is not None
    assert "moat" in reason.lower()


# ----------------------------------------------------------------------
# monetization
# ----------------------------------------------------------------------


def test_rejects_invalid_monetization_value() -> None:
    out, reason = validate_candidate(
        _good_candidate(monetization="ads"), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "monetization" in reason


def test_rejects_missing_monetization() -> None:
    raw = _good_candidate()
    del raw["monetization"]

    out, reason = validate_candidate(raw, negative_names=[])

    assert out is None
    assert reason is not None
    assert "monetization" in reason


def test_rejects_null_monetization() -> None:
    out, reason = validate_candidate(
        _good_candidate(monetization=None), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "monetization" in reason


def test_accepts_all_allowed_monetization_values() -> None:
    for value in sorted(ALLOWED_MONETIZATION):
        out, reason = validate_candidate(
            _good_candidate(monetization=value), negative_names=[]
        )

        assert reason is None, f"{value!r}: {reason}"
        assert out is not None
        assert out["monetization"] == value


# ----------------------------------------------------------------------
# name
# ----------------------------------------------------------------------


def test_rejects_empty_name() -> None:
    out, reason = validate_candidate(
        _good_candidate(name=""), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "name" in reason


def test_rejects_whitespace_only_name() -> None:
    out, reason = validate_candidate(
        _good_candidate(name="   "), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "name" in reason


def test_rejects_non_string_name() -> None:
    out, reason = validate_candidate(
        _good_candidate(name=123), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "name" in reason


# ----------------------------------------------------------------------
# Optional fields type-check
# ----------------------------------------------------------------------


def test_accepts_null_optional_fields() -> None:
    out, reason = validate_candidate(
        _good_candidate(
            one_liner=None,
            target_user=None,
            why_different=None,
            killer_use_case=None,
            estimated_mvp_hours=None,
        ),
        negative_names=[],
    )

    assert reason is None
    assert out is not None
    assert out["one_liner"] is None
    assert out["estimated_mvp_hours"] is None


def test_rejects_non_int_estimated_mvp_hours() -> None:
    out, reason = validate_candidate(
        _good_candidate(estimated_mvp_hours="40"), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "estimated_mvp_hours" in reason


def test_rejects_non_string_one_liner() -> None:
    out, reason = validate_candidate(
        _good_candidate(one_liner=42), negative_names=[]
    )

    assert out is None
    assert reason is not None
    assert "one_liner" in reason
