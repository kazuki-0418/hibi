from __future__ import annotations

import os
from typing import Iterator
from unittest.mock import MagicMock

import pytest

# Must be set before anything imports `app.settings` or `app.rate_limit`.
os.environ.setdefault("CLICK_SIGNING_SECRET", "test-secret-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("PUBLIC_BASE_URL", "https://newspaper.test")
os.environ.setdefault("IP_SALT", "test-ip-salt-0123456789")
os.environ.setdefault("MISSING_REDIRECT_URL", "https://newspaper.test/missing")
# Tests default to the prod 60/minute limit; the one test that cares about
# the 429 path sets CLICK_RATE_LIMIT before import and reloads the module.
os.environ.setdefault("CLICK_RATE_LIMIT", "60/minute")


@pytest.fixture
def db_stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Replace the db module's functions with mocks and skip pool init."""
    from app import db as db_module

    fake = MagicMock()
    fake.get_article.return_value = {
        "url": "https://origin.example.com/article",
        "user_id": "00000000-0000-0000-0000-000000000001",
    }
    fake.get_article_with_edition.return_value = {
        "url": "https://origin.example.com/article",
        "user_id": "00000000-0000-0000-0000-000000000001",
        "issue_no": 17,
        "position_in_edition": 3,
    }
    fake.log_click.return_value = None

    monkeypatch.setattr(db_module, "get_article", fake.get_article)
    monkeypatch.setattr(
        db_module, "get_article_with_edition", fake.get_article_with_edition
    )
    monkeypatch.setattr(db_module, "log_click", fake.log_click)
    monkeypatch.setattr(db_module, "init_pool", lambda *_a, **_kw: None)
    monkeypatch.setattr(db_module, "close_pool", lambda: None)

    yield fake


@pytest.fixture
def app_client(db_stub: MagicMock):
    """Fresh FastAPI app + TestClient per test."""
    from fastapi.testclient import TestClient

    from app.main import _build_app
    from app.rate_limit import limiter
    from app.settings import Settings

    limiter.reset()

    settings = Settings()
    app = _build_app(settings)

    with TestClient(app) as client:
        yield client, db_stub, settings
