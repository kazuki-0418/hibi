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


def _extract_yaml_block(raw: str) -> str:
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1)
    return raw


def parse_packet(raw: str) -> dict[str, Any]:
    text = _extract_yaml_block(raw)
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ParseError(f"YAML 解析失敗: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ParseError("packet が dict ではない")
    missing = [k for k in _REQUIRED_KEYS if k not in loaded]
    if missing:
        raise ParseError(f"必須フィールド欠落: {missing}")
    return loaded
