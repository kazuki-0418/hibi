"""Tests for `idea_mining.ideator` system-prompt assembly.

Issue #138 acceptance: profile/user-constraints.md と
profile/negative-examples.md を prompt 先頭に必ず注入する。pattern.pain も
user message に含める。
"""
from __future__ import annotations

import pytest

from idea_mining.ideator import (
    build_system_prompt,
    build_user_message,
)
from idea_mining.prompts.ideator import SYSTEM_PROMPT_TEMPLATE


PROFILE_FIXTURE = """\
# User Constraints

- 必須項目: 個人プロジェクト前提で運用できること
- 学習信号はクリックのみ

# Negative Examples

## Aesthetic OS
- 理由: コンセプトが先行し、実運用での学習信号が貧弱
"""


# ----------------------------------------------------------------------
# build_system_prompt
# ----------------------------------------------------------------------


def test_build_system_prompt_injects_profile_block_at_head() -> None:
    prompt = build_system_prompt(PROFILE_FIXTURE)

    # Profile block appears literally in the prompt.
    assert PROFILE_FIXTURE in prompt
    # The profile is in the *head* of the prompt — before the rule block.
    profile_idx = prompt.index(PROFILE_FIXTURE)
    rules_idx = prompt.index("For the input pattern")
    assert profile_idx < rules_idx, (
        "profile_block must precede the rule list in the system prompt"
    )


def test_build_system_prompt_contains_user_constraints_marker() -> None:
    prompt = build_system_prompt(PROFILE_FIXTURE)
    assert "必須項目: 個人プロジェクト前提で運用できること" in prompt


def test_build_system_prompt_contains_negative_examples_marker() -> None:
    prompt = build_system_prompt(PROFILE_FIXTURE)
    assert "Aesthetic OS" in prompt


def test_build_system_prompt_lists_allowed_monetization_values() -> None:
    prompt = build_system_prompt(PROFILE_FIXTURE)
    for value in ("subscription", "one-time", "affiliate", "freemium", "b2b"):
        assert value in prompt


def test_build_system_prompt_lists_allowed_llm_moat_conditions() -> None:
    prompt = build_system_prompt(PROFILE_FIXTURE)
    for value in (
        "workflow",
        "data",
        "distribution",
        "trust",
        "network",
        "physical",
        "regulatory",
    ):
        assert value in prompt


def test_build_system_prompt_demands_5_to_10_candidates() -> None:
    prompt = build_system_prompt(PROFILE_FIXTURE)
    assert "5-10 candidates" in prompt


def test_build_system_prompt_rejects_empty_profile() -> None:
    with pytest.raises(ValueError, match="profile_block is empty"):
        build_system_prompt("")


def test_build_system_prompt_rejects_whitespace_only_profile() -> None:
    with pytest.raises(ValueError, match="profile_block is empty"):
        build_system_prompt("   \n\n\t")


# ----------------------------------------------------------------------
# build_user_message
# ----------------------------------------------------------------------


def test_build_user_message_contains_pain() -> None:
    pattern = {"id": "11111111-1111-1111-1111-111111111111", "pain": "重複の SaaS 課金がしんどい"}

    msg = build_user_message(pattern)

    assert "重複の SaaS 課金がしんどい" in msg


def test_build_user_message_asks_for_json_only() -> None:
    pattern = {"id": "11111111-1111-1111-1111-111111111111", "pain": "x"}

    msg = build_user_message(pattern)

    assert "JSON" in msg
    assert "candidates" in msg


# ----------------------------------------------------------------------
# Template contract (snapshot-style — guard against drift)
# ----------------------------------------------------------------------


def test_system_prompt_template_contains_single_profile_block_placeholder() -> None:
    # `.format()` must substitute exactly one {profile_block}; literal braces
    # in the JSON schema example must stay doubled.
    assert SYSTEM_PROMPT_TEMPLATE.count("{profile_block}") == 1


def test_system_prompt_template_renders_without_keyerror() -> None:
    # Cheap snapshot: confirms double-braces in the output JSON example are
    # preserved (otherwise `.format` would KeyError on the embedded keys).
    rendered = SYSTEM_PROMPT_TEMPLATE.format(profile_block="STUB")
    assert "STUB" in rendered
    assert '"candidates"' in rendered
    assert '"llm_moat_conditions"' in rendered
