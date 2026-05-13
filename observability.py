"""Sentry initialization for the daily-news pipeline (root-level scripts).

Kept separate from `service/app/observability.py` because the service has
its own pyproject.toml and is deployed independently. The two scrubbers
differ in scope: this one focuses on the recipient email and SMTP errors
that the pipeline can emit, since there is no HTTP request context here.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import sentry_sdk

log = logging.getLogger(__name__)

# Crude — good enough to redact a recipient address that leaked into an
# exception message or breadcrumb. Not a general PII detector.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _redact_emails(text: str) -> str:
    return _EMAIL_RE.sub("[redacted-email]", text)


def scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> Optional[dict[str, Any]]:
    """before_send hook: redact email addresses from messages and breadcrumbs."""
    msg = event.get("message")
    if isinstance(msg, str):
        event["message"] = _redact_emails(msg)

    exc_values = event.get("exception", {}).get("values")
    if isinstance(exc_values, list):
        for exc in exc_values:
            if isinstance(exc, dict):
                value = exc.get("value")
                if isinstance(value, str):
                    exc["value"] = _redact_emails(value)

    crumbs = event.get("breadcrumbs", {}).get("values")
    if isinstance(crumbs, list):
        for crumb in crumbs:
            if isinstance(crumb, dict):
                message = crumb.get("message")
                if isinstance(message, str):
                    crumb["message"] = _redact_emails(message)

    return event


def init_sentry_from_env() -> bool:
    """Initialize Sentry from environment. Returns True if active.

    Env vars (all optional):
    - SENTRY_DSN: enables Sentry; unset → no-op
    - HIBI_RELEASE: release tag (default "dev"; set to git SHA in CI)
    - HIBI_ENV: environment tag (default "production")
    """
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.info("sentry: SENTRY_DSN unset — pipeline observability disabled")
        return False

    sentry_sdk.init(
        dsn=dsn,
        release=os.environ.get("HIBI_RELEASE", "dev"),
        environment=os.environ.get("HIBI_ENV", "production"),
        # Pipeline is short-lived; traces add no value for batch jobs.
        traces_sample_rate=0.0,
        send_default_pii=False,
        before_send=scrub_event,
    )
    sentry_sdk.set_tag("pipeline", "daily_news")
    log.info("sentry: pipeline initialized")
    return True
