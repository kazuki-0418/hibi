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


def _extract_yaml_block(raw: str) -> str:
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1)
    return raw


def _quote_unsafe_list_items(text: str) -> str:
    r"""Defensive preprocessor: wrap every `- foo` item in single quotes.

    /make-execution-packet outputs free-form Japanese acceptance_criteria that
    routinely embed `[jp]` / `country: [jp]` / backticked code refs / mid-line
    `"quoted phrases"` continued with more text. Each of these breaks
    safe_load. The packet schema only uses lists of strings (not lists of
    mappings), so blanket-quoting list items is safe and covers all
    YAML-significant-character failure modes in one pass.
    """
    out: list[str] = []
    for line in text.split("\n"):
        m = _LIST_ITEM_RE.match(line)
        if m:
            content = m.group(2).replace("'", "''")
            out.append(f"{m.group(1)}'{content}'")
        else:
            out.append(line)
    return "\n".join(out)


def parse_packet(raw: str) -> dict[str, Any]:
    text = _extract_yaml_block(raw)
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        try:
            loaded = yaml.safe_load(_quote_unsafe_list_items(text))
        except yaml.YAMLError as exc:
            raise ParseError(f"YAML 解析失敗: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ParseError("packet が dict ではない")
    missing = [k for k in _REQUIRED_KEYS if k not in loaded]
    if missing:
        raise ParseError(f"必須フィールド欠落: {missing}")
    return loaded
