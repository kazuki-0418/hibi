from __future__ import annotations

import hashlib

import psycopg

from app.signing import sign_article

ARTICLE_ID = "11111111-1111-1111-1111-111111111111"
SECRET = "test-secret-0123456789abcdef"


def _valid_sig() -> str:
    return sign_article(ARTICLE_ID, SECRET)


def test_valid_signature_redirects_and_logs_click(app_client):
    client, db, _settings = app_client

    r = client.get(
        f"/r/{ARTICLE_ID}",
        params={"s": _valid_sig()},
        follow_redirects=False,
        headers={"user-agent": "Mozilla/5.0 human", "cf-connecting-ip": "203.0.113.10"},
    )

    assert r.status_code == 302
    assert r.headers["location"] == "https://origin.example.com/article"
    db.log_click.assert_called_once()
    call_kwargs = db.log_click.call_args.kwargs
    assert call_kwargs["article_id"] == ARTICLE_ID
    assert call_kwargs["user_id"] == "00000000-0000-0000-0000-000000000001"
    assert call_kwargs["user_agent"] == "Mozilla/5.0 human"
    # ip_hash is SHA-256 truncated to 32 hex chars, never the raw IP
    assert len(call_kwargs["ip_hash"]) == 32
    assert "203.0.113.10" not in call_kwargs["ip_hash"]
    expected_hash = hashlib.sha256("203.0.113.10|test-ip-salt-0123456789".encode()).hexdigest()[:32]
    assert call_kwargs["ip_hash"] == expected_hash


def test_invalid_signature_redirects_without_logging(app_client):
    client, db, _ = app_client

    r = client.get(
        f"/r/{ARTICLE_ID}",
        params={"s": "X" * 22},
        follow_redirects=False,
        headers={"user-agent": "Mozilla/5.0 human", "cf-connecting-ip": "203.0.113.11"},
    )

    assert r.status_code == 302
    assert r.headers["location"] == "https://origin.example.com/article"
    db.log_click.assert_not_called()


def test_prefetch_user_agent_skips_logging(app_client):
    client, db, _ = app_client

    r = client.get(
        f"/r/{ARTICLE_ID}",
        params={"s": _valid_sig()},
        follow_redirects=False,
        headers={
            "user-agent": "Mozilla/5.0 (compatible; GoogleImageProxy)",
            "cf-connecting-ip": "203.0.113.12",
        },
    )

    assert r.status_code == 302
    assert r.headers["location"] == "https://origin.example.com/article"
    db.log_click.assert_not_called()


def test_missing_article_redirects_to_missing_page(app_client):
    client, db, settings = app_client
    db.get_article.return_value = None

    r = client.get(
        f"/r/{ARTICLE_ID}",
        params={"s": _valid_sig()},
        follow_redirects=False,
        headers={"user-agent": "Mozilla/5.0 human", "cf-connecting-ip": "203.0.113.13"},
    )

    assert r.status_code == 302
    assert r.headers["location"] == settings.missing_redirect_url
    db.log_click.assert_not_called()


def test_db_cold_start_falls_back_to_missing_redirect(
    app_client, monkeypatch
):
    """Neon scale-to-zero cold start path: the real get_article catches
    psycopg.OperationalError internally and returns None, so the click handler
    must 302 to missing_redirect_url rather than 500.

    This exercises the real db.get_article through the route by re-importing
    a fresh app.db (the conftest db_stub mocked the module-level attribute);
    we then point the pool at a stub that raises on .connection(). log_click
    stays mocked at the conftest layer so we never hit a real DB.
    """
    import importlib

    client, db_stub_mock, settings = app_client

    from app import db as db_module
    real_db = importlib.reload(db_module)

    class _PoolRaising:
        def connection(self) -> object:
            raise psycopg.OperationalError("connection closed (cold start)")

        def close(self) -> None:
            return None

    monkeypatch.setattr(real_db, "_pool", _PoolRaising())
    # After importlib.reload, db_module.get_article is the real function again
    # (the conftest mock was discarded). The click route imported
    # `from .. import db`, so it sees the reloaded module attribute directly.

    r = client.get(
        f"/r/{ARTICLE_ID}",
        params={"s": _valid_sig()},
        follow_redirects=False,
        headers={"user-agent": "Mozilla/5.0 human", "cf-connecting-ip": "203.0.113.14"},
    )

    assert r.status_code == 302
    assert r.headers["location"] == settings.missing_redirect_url
    db_stub_mock.log_click.assert_not_called()


def test_rate_limit_returns_429_after_threshold(app_client):
    """60/minute per-IP: the 61st request from the same IP must 429."""
    client, _db, _settings = app_client

    headers = {"user-agent": "Mozilla/5.0 human", "cf-connecting-ip": "203.0.113.99"}
    params = {"s": _valid_sig()}

    for i in range(60):
        r = client.get(f"/r/{ARTICLE_ID}", params=params, follow_redirects=False, headers=headers)
        assert r.status_code == 302, f"request {i + 1} expected 302, got {r.status_code}"

    r = client.get(f"/r/{ARTICLE_ID}", params=params, follow_redirects=False, headers=headers)
    assert r.status_code == 429
