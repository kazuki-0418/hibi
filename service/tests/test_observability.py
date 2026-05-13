"""Unit tests for the Sentry init + PII scrubber.

We do NOT want real Sentry traffic in tests, so init is only exercised
through scrub_event() directly (no DSN) plus a single init/no-init path
check via monkeypatch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.observability import init_sentry, scrub_event


def _evt(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "request": {
            "env": {"REMOTE_ADDR": "203.0.113.42"},
            "headers": {
                "X-Forwarded-For": "203.0.113.42, 198.51.100.7",
                "CF-Connecting-IP": "203.0.113.42",
                "User-Agent": "Mozilla/5.0",
            },
            "cookies": {"session": "secret-token"},
            "url": "https://api.hibi-news.com/r/abc123?s=hmac-sig-value",
            "query_string": "s=hmac-sig-value",
        },
        "user": {
            "ip_address": "203.0.113.42",
            "email": "kazuki.castle0418@gmail.com",
            "id": "00000000-0000-0000-0000-000000000001",
        },
    }
    base.update(overrides)
    return base


def test_scrub_removes_remote_addr_from_env() -> None:
    out = scrub_event(_evt(), {})
    assert out is not None
    assert "REMOTE_ADDR" not in out["request"]["env"]


def test_scrub_removes_ip_headers_case_insensitive() -> None:
    out = scrub_event(_evt(), {})
    assert out is not None
    headers = out["request"]["headers"]
    assert "X-Forwarded-For" not in headers
    assert "CF-Connecting-IP" not in headers
    # Benign headers survive — User-Agent is useful for triage.
    assert headers.get("User-Agent") == "Mozilla/5.0"


def test_scrub_drops_cookies_entirely() -> None:
    out = scrub_event(_evt(), {})
    assert out is not None
    assert "cookies" not in out["request"]


def test_scrub_strips_query_string_from_url() -> None:
    """HMAC signatures must not leave the process."""
    out = scrub_event(_evt(), {})
    assert out is not None
    assert out["request"]["url"] == "https://api.hibi-news.com/r/abc123"
    assert "query_string" not in out["request"]


def test_scrub_removes_user_ip_and_email_but_keeps_id() -> None:
    out = scrub_event(_evt(), {})
    assert out is not None
    user = out["user"]
    assert "ip_address" not in user
    assert "email" not in user
    assert user["id"] == "00000000-0000-0000-0000-000000000001"


def test_scrub_handles_event_without_request_or_user() -> None:
    """Defensive: event shape varies (exceptions outside a request scope)."""
    out = scrub_event({"message": "boom"}, {})
    assert out == {"message": "boom"}


def test_init_sentry_returns_false_when_dsn_missing() -> None:
    assert init_sentry(None, release="dev", environment="test") is False
    assert init_sentry("", release="dev", environment="test") is False


def test_init_sentry_calls_sdk_init_when_dsn_present() -> None:
    with patch("app.observability.sentry_sdk.init") as mock_init:
        ok = init_sentry(
            "https://key@sentry.io/123",
            release="abc123",
            environment="production",
            traces_sample_rate=0.05,
        )

    assert ok is True
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["dsn"] == "https://key@sentry.io/123"
    assert kwargs["release"] == "abc123"
    assert kwargs["environment"] == "production"
    assert kwargs["traces_sample_rate"] == 0.05
    assert kwargs["send_default_pii"] is False
    assert kwargs["before_send"] is scrub_event
