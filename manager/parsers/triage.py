from __future__ import annotations

import json
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

_READINESS_VALUES: frozenset[TriageReadiness] = frozenset(
    ("ready", "needs-confirmation", "do-not-run")
)
_CLASSIFICATION_VALUES: frozenset[str] = frozenset(
    ("auto-fixable", "confirm-first", "blocked")
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


def parse_triage_json(raw: str) -> TriageReadiness:
    """Parse Structured Outputs (`claude -p --json-schema schemas/triage.json`).

    CLI enforces `additionalProperties: false` + required fields, but we still
    validate the enum at the boundary because:
      - the `claude -p --output-format json` envelope is unwrapped upstream
        into `raw_stdout`; a malformed payload (or a CLI version that doesn't
        enforce the schema) reaches us as plain text
      - parse failures must surface as ParseError, not silent fallbacks
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"triage 出力が JSON ではない: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ParseError("triage 出力が object ではない")
    value = payload.get("execution_readiness")
    if value not in _READINESS_VALUES:
        raise ParseError(
            f"execution_readiness が enum 外: {value!r}"
        )
    return value  # type: ignore[return-value]


def parse_classification_json(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("classification")
    if value in _CLASSIFICATION_VALUES:
        return value  # type: ignore[no-any-return]
    return None
