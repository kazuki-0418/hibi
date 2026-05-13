"""GET /r/{article_id}?s=<sig> — signed click tracker."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..rate_limit import CLICK_RATE_LIMIT, limiter
from ..settings import Settings
from ..signing import verify

log = logging.getLogger(__name__)

router = APIRouter()

# UA substrings that indicate link prefetching / bot fetch — these requests
# must not be counted as human clicks.
PREFETCH_UA_PATTERNS = (
    "GoogleImageProxy",
    "YahooMailProxy",
    "bingbot",
    "Googlebot",
    "Slackbot",
    "facebookexternalhit",
    "Twitterbot",
    "LinkedInBot",
    "Discordbot",
)


def _hash_ip(ip: str, salt: str) -> str:
    return hashlib.sha256(f"{ip}|{salt}".encode()).hexdigest()[:32]


def _is_prefetch(user_agent: str) -> bool:
    return any(p in user_agent for p in PREFETCH_UA_PATTERNS)


@router.get("/r/{article_id}")
@limiter.limit(CLICK_RATE_LIMIT)
def click(
    article_id: str,
    s: str,
    request: Request,
    to: str | None = None,
) -> RedirectResponse:
    """Signed redirect.

    Default mode: 302 to the article's external source URL and record the
    click in `clicks` (subject to HMAC verify + UA/prefetch filtering).

    `?to=edition`: 302 to the internal edition page anchor
    (`<web_base_url>/edition/NNNN/#story-N`). HMAC is still required to
    prevent tampering, but the click is **not** recorded — internal clicks
    are weak learning signal (see issue #55).

    On missing article / missing edition / any DB error, fall back to
    `settings.missing_redirect_url` (302).
    """
    settings: Settings = request.app.state.settings

    if to == "edition":
        return _redirect_to_edition(article_id, s, settings)

    article = db.get_article(article_id)
    if article is None:
        return RedirectResponse(settings.missing_redirect_url, status_code=302)

    ua = request.headers.get("user-agent", "")

    if not verify(article_id, s, settings.click_signing_secret):
        # Bad signature — 302 to the real URL anyway so an attacker can't
        # distinguish "signature rejected" from "click logged", but do not
        # record the click.
        log.info("click: bad signature for article_id=%s", article_id)
        return RedirectResponse(article["url"], status_code=302)

    if _is_prefetch(ua):
        log.info("click: prefetch/bot UA skipped logging for article_id=%s", article_id)
        return RedirectResponse(article["url"], status_code=302)

    client_ip = _resolve_client_ip(request)
    try:
        db.log_click(
            article_id=article_id,
            user_id=article["user_id"],
            user_agent=ua[:512],
            ip_hash=_hash_ip(client_ip, settings.ip_salt),
        )
    except Exception:
        # Don't fail the redirect if click logging misbehaves — the UX cost
        # of a broken link far exceeds the analytics cost of a missed row.
        log.exception("click: failed to log click for article_id=%s", article_id)

    return RedirectResponse(article["url"], status_code=302)


def _redirect_to_edition(
    article_id: str, s: str, settings: Settings
) -> RedirectResponse:
    """Handle `/r/{id}?to=edition`.

    On missing article / missing edition info → missing_redirect_url.
    On HMAC failure → fall through to the article's external URL (same
    contract as the default branch: don't leak signature-verified vs not).
    On success → 302 to `<web_base_url>/edition/NNNN/#story-N`. No click
    is recorded (internal clicks are not a useful learning signal).
    """
    article = db.get_article_with_edition(article_id)
    if article is None:
        return RedirectResponse(settings.missing_redirect_url, status_code=302)

    if not verify(article_id, s, settings.click_signing_secret):
        log.info(
            "click[edition]: bad signature for article_id=%s", article_id
        )
        return RedirectResponse(article["url"], status_code=302)

    issue_no = article["issue_no"]
    position = article["position_in_edition"]
    if issue_no is None or position is None:
        # Orphan article (edition_id NULL, or FK pointing at a missing row).
        log.info(
            "click[edition]: missing edition info for article_id=%s "
            "(issue_no=%s, position=%s)",
            article_id,
            issue_no,
            position,
        )
        return RedirectResponse(settings.missing_redirect_url, status_code=302)

    base = settings.web_base_url.rstrip("/")
    target = f"{base}/edition/{issue_no:04d}/#story-{position}"
    return RedirectResponse(target, status_code=302)


def _resolve_client_ip(request: Request) -> str:
    """Prefer Cloudflare's CF-Connecting-IP, fall back to direct peer."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    if request.client is not None:
        return request.client.host
    return "0.0.0.0"
