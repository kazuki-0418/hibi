from __future__ import annotations

import re
from typing import Any

import yaml

from . import ParseError

_REQUIRED_KEYS: tuple[str, ...] = (
    "issue_id",
    "title",
    "classification",
    "scope",
    "goal",
    "acceptance_criteria",
    "constraints",
    "impacted_areas",
    "target_tests",
    "stop_conditions",
    "out_of_scope",
)

_FENCE_RE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
# Match any non-empty `- foo` list item (no restriction on starting char).
# The fallback path only runs when the initial parse already failed, so we
# can quote aggressively without worrying about over-quoting valid YAML.
_LIST_ITEM_RE = re.compile(r"^(\s*-\s+)(.+?)\s*$")
# Top-level scalar string keys (excluding issue_id which is int) — used by
# fallback to quote inline values that contain YAML-significant chars like
# `title: feat(idea-mining): Critic` (double colon trips safe_load).
_TOP_LEVEL_STRING_KEYS: tuple[str, ...] = (
    "title", "classification", "scope", "goal",
)
_TOP_LEVEL_KV_RE = re.compile(
    r"^(" + "|".join(_TOP_LEVEL_STRING_KEYS) + r"):\s+(.+?)\s*$"
)


def _extract_yaml_block(raw: str) -> str:
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1)
    return raw


def _quote_unsafe_yaml(text: str) -> str:
    r"""Defensive preprocessor: wrap list items AND top-level string fields
    (title / classification / scope / goal) in single quotes.

    Failure modes seen in production:
    - acceptance_criteria 配下の `- country: [jp]` / `- "wrapper" 型...`
      (list item の中の `: ` / `[...]` / 中途半端な double quote)
    - top-level `title: feat(idea-mining): Critic ...` (conventional commit
      prefix の `:` が二重 colon になり mapping 解釈で爆発)

    packet schema は list of strings + top-level scalars (string + int) のみ。
    list of mappings は無いので blanket quoting で安全。issue_id だけは
    int として残したいので _TOP_LEVEL_STRING_KEYS から除外。
    """
    out: list[str] = []
    for line in text.split("\n"):
        m_list = _LIST_ITEM_RE.match(line)
        if m_list:
            content = m_list.group(2).replace("'", "''")
            out.append(f"{m_list.group(1)}'{content}'")
            continue
        m_kv = _TOP_LEVEL_KV_RE.match(line)
        if m_kv:
            value = m_kv.group(2).replace("'", "''")
            out.append(f"{m_kv.group(1)}: '{value}'")
            continue
        out.append(line)
    return "\n".join(out)


def parse_packet(raw: str) -> dict[str, Any]:
    text = _extract_yaml_block(raw)
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        try:
            loaded = yaml.safe_load(_quote_unsafe_yaml(text))
        except yaml.YAMLError as exc:
            raise ParseError(f"YAML 解析失敗: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ParseError("packet が dict ではない")
    missing = [k for k in _REQUIRED_KEYS if k not in loaded]
    if missing:
        raise ParseError(f"必須フィールド欠落: {missing}")
    return loaded
