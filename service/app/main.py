from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import db
from .rate_limit import limiter
from .routes import click
from .settings import Settings


def _build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        db.init_pool(settings.database_url)
        try:
            yield
        finally:
            db.close_pool()

    is_prod = settings.app_env.lower() == "production"
    app = FastAPI(
        title="Personal AI Newspaper API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url=None if is_prod else "/openapi.json",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
    )
    app.state.settings = settings
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(click.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    return app


app = _build_app()
