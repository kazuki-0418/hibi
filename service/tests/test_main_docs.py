from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import _build_app
from app.settings import Settings


def _client_with_app_env(monkeypatch: pytest.MonkeyPatch, app_env: str | None) -> TestClient:
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    settings = Settings()
    app = _build_app(settings)
    return TestClient(app)


@pytest.mark.parametrize("app_env", [None, "development", "staging", "prod"])
def test_docs_exposed_when_not_production(
    monkeypatch: pytest.MonkeyPatch, db_stub: MagicMock, app_env: str | None
) -> None:
    with _client_with_app_env(monkeypatch, app_env) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize("app_env", ["production", "PRODUCTION", "Production"])
def test_docs_disabled_in_production(
    monkeypatch: pytest.MonkeyPatch, db_stub: MagicMock, app_env: str
) -> None:
    with _client_with_app_env(monkeypatch, app_env) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/health").status_code == 200
