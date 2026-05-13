from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    # HMAC secret used to sign /r/{article_id} URLs. No default: unset → startup fail.
    click_signing_secret: str = Field(..., min_length=16)

    # Postgres (Neon). Same DATABASE_URL the batch uses.
    database_url: str = Field(...)

    # Public-facing base URL the email links point at, e.g. https://newspaper.<domain>
    public_base_url: str = Field(...)

    # Public-facing base URL of the *web archive* (Astro site on hibi-news.com).
    # Distinct from `public_base_url` (api.hibi-news.com) so internal click
    # redirects to /edition/NNNN/ do not accidentally route through the API host.
    web_base_url: str = "https://hibi-news.com"

    # Salt for SHA-256(ip || salt). Rotate periodically to break long-term tracking.
    ip_salt: str = Field(..., min_length=8)

    # Redirect target when article_id does not exist in DB.
    missing_redirect_url: str = "https://newspaper.invalid/missing"

    # Rate limit for /r/{id}. Read from env at rate_limit.py import time;
    # kept here too so /health can echo it if needed later.
    click_rate_limit: str = "60/minute"

    # Sentry. Optional — unset → no-op (local dev / CI without secrets).
    sentry_dsn: str | None = None
    # Release identifier (git SHA in CI, "dev" locally).
    hibi_release: str = "dev"
    # Sentry environment tag. Distinct from app_env so we can run in dev mode
    # but still report to the production Sentry project if desired.
    hibi_env: str = "production"
    # Performance traces sample rate. Keep low to fit the free-tier quota.
    sentry_traces_sample_rate: float = 0.1
