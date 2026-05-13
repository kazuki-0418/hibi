"""Sentry initialization for the FastAPI service.

`SENTRY_DSN` is optional — when unset, init_sentry() is a no-op so local
dev / CI without secrets keeps working. PII is scrubbed defensively before
events leave the process even though send_default_pii is False, because
the click route may have IP and signed-URL query strings in breadcrumbs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

log = logging.getLogger(__name__)

# Header keys that may carry a raw client IP. Sentry strips these when
# send_default_pii=False, but we belt-and-suspenders in before_send too.
_IP_HEADERS = ("x-forwarded-for", "cf-connecting-ip", "x-real-ip", "true-client-ip")


def scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> Optional[dict[str, Any]]:
    """before_send hook: drop raw IPs, cookies, and signed-URL query strings."""
    request = event.get("request")
    if isinstance(request, dict):
        # Drop raw IP that Sentry's wsgi/asgi auto-collects.
        env = request.get("env")
        if isinstance(env, dict):
            env.pop("REMOTE_ADDR", None)

        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if key.lower() in _IP_HEADERS:
                    headers.pop(key, None)

        # Cookies can carry session tokens — drop entirely.
        request.pop("cookies", None)

        # Strip query string from URL so HMAC signatures don't leak.
        url = request.get("url")
        if isinstance(url, str) and "?" in url:
            request["url"] = url.split("?", 1)[0]
        request.pop("query_string", None)

    user = event.get("user")
    if isinstance(user, dict):
        user.pop("ip_address", None)
        user.pop("email", None)

    return event


def init_sentry(
    dsn: Optional[str],
    *,
    release: str,
    environment: str,
    traces_sample_rate: float = 0.1,
) -> bool:
    """Initialize Sentry if a DSN is provided. Returns True if initialized."""
    if not dsn:
        log.info("sentry: SENTRY_DSN unset — observability disabled")
        return False

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FastApiIntegration(), StarletteIntegration()],
        release=release,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        before_send=scrub_event,
    )
    log.info("sentry: initialized (env=%s release=%s)", environment, release)
    return True
