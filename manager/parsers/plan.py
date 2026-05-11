from __future__ import annotations

import re

from . import ParseError
from ..types import PlanRecommendation

_REC_RE = re.compile(
    r"#\s*Recommendation\s*\n+\s*-?\s*(proceed with caution|confirm first|proceed)\b",
    re.IGNORECASE,
)


def parse_plan(raw: str) -> PlanRecommendation:
    m = _REC_RE.search(raw)
    if not m:
        raise ParseError("Recommendation 行が見つからない")
    value = m.group(1).lower()
    if value == "proceed":
        return "proceed"
    if value == "proceed with caution":
        return "proceed with caution"
    return "confirm first"
