from __future__ import annotations

import re

from . import ParseError
from ..types import TriageReadiness

_READINESS_RE = re.compile(
    r"#\s*Execution\s+Readiness\s*\n+\s*-\s*(ready|needs-confirmation|do-not-run)\b",
    re.IGNORECASE,
)
_CLASSIFICATION_RE = re.compile(
    r"#\s*Classification\s*\n+\s*-\s*(auto-fixable|confirm-first|blocked)\b",
    re.IGNORECASE,
)


def parse_triage(raw: str) -> TriageReadiness:
    m = _READINESS_RE.search(raw)
    if not m:
        raise ParseError("Execution Readiness 行が見つからない")
    value = m.group(1).lower()
    if value == "ready":
        return "ready"
    if value == "needs-confirmation":
        return "needs-confirmation"
    return "do-not-run"


def parse_classification(raw: str) -> str | None:
    m = _CLASSIFICATION_RE.search(raw)
    return m.group(1).lower() if m else None
