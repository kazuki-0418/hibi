"""Unit tests for the pipeline-side Sentry scrubber + init switch."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from observability import _redact_emails, init_sentry_from_env, scrub_event


def test_redact_emails_replaces_all_addresses() -> None:
    text = "send to kazuki@example.com failed; also a@b.co bounced"
    out = _redact_emails(text)
    assert "kazuki@example.com" not in out
    assert "a@b.co" not in out
    assert out.count("[redacted-email]") == 2


def test_redact_emails_passes_text_without_addresses() -> None:
    assert _redact_emails("nothing here") == "nothing here"


def test_scrub_event_redacts_message() -> None:
    event: dict[str, Any] = {"message": "SMTP failed for kazuki@example.com"}
    out = scrub_event(event, {})
    assert out is not None
    assert out["message"] == "SMTP failed for [redacted-email]"


def test_scrub_event_redacts_exception_value() -> None:
    event: dict[str, Any] = {
        "exception": {
            "values": [
                {"type": "SMTPError", "value": "Bad recipient kazuki@example.com"}
            ]
        }
    }
    out = scrub_event(event, {})
    assert out is not None
    val = out["exception"]["values"][0]["value"]
    assert "kazuki@example.com" not in val
    assert "[redacted-email]" in val


def test_scrub_event_redacts_breadcrumb_message() -> None:
    event: dict[str, Any] = {
        "breadcrumbs": {
            "values": [
                {"message": "to=kazuki@example.com"},
                {"message": "no email here"},
            ]
        }
    }
    out = scrub_event(event, {})
    assert out is not None
    crumbs = out["breadcrumbs"]["values"]
    assert "[redacted-email]" in crumbs[0]["message"]
    assert crumbs[1]["message"] == "no email here"


def test_scrub_event_handles_minimal_event_shape() -> None:
    assert scrub_event({"level": "error"}, {}) == {"level": "error"}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SENTRY_DSN", "HIBI_RELEASE", "HIBI_ENV"):
        monkeypatch.delenv(key, raising=False)


def test_init_returns_false_when_dsn_missing(clean_env: None) -> None:
    assert init_sentry_from_env() is False


def test_init_calls_sdk_init_with_env_values(
    monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.io/42")
    monkeypatch.setenv("HIBI_RELEASE", "abc123")
    monkeypatch.setenv("HIBI_ENV", "production")

    with patch("observability.sentry_sdk.init") as mock_init, patch(
        "observability.sentry_sdk.set_tag"
    ) as mock_tag:
        ok = init_sentry_from_env()

    assert ok is True
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["dsn"] == "https://key@sentry.io/42"
    assert kwargs["release"] == "abc123"
    assert kwargs["environment"] == "production"
    assert kwargs["traces_sample_rate"] == 0.0
    assert kwargs["send_default_pii"] is False
    assert kwargs["before_send"] is scrub_event
    mock_tag.assert_called_once_with("pipeline", "daily_news")


def test_init_defaults_release_and_env_when_unset(
    monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.io/42")
    with patch("observability.sentry_sdk.init") as mock_init, patch(
        "observability.sentry_sdk.set_tag"
    ):
        init_sentry_from_env()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["release"] == "dev"
    assert kwargs["environment"] == "production"
