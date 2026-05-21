"""AppFollow API v2 fetcher — ★1-4 customer reviews into `voices`.

各 (country, app_id) について AppFollow Free プランの Reviews endpoint
(`GET https://api.appfollow.io/api/v2/reviews`) を叩き、★1-4 のレビュー
だけを `voices` テーブルに insert する。★5 は INSERT 前に除外し、
元の rating は `meta.rating` (1-5) に保持する。

Apple iTunes Customer Reviews RSS が死状態に陥った 2026-05-21 以降の
代替経路 (Issue #150, ADR: 10_projects/idea-mining/decisions/
2026-05-21-appfollow-free-personal-use.md)。AppFollow Free は 2 apps cap /
直近 50 件 / 7 日履歴 / 500 credits/月 / 10 credits/req。

newspaper pipeline (`daily_news.py` / `articles` / mailer / archive) からは
独立した経路。失敗してもニュースレターには影響しない。

Idempotency:
    INSERT は `ON CONFLICT (source, source_id) DO NOTHING` で、同一 (source,
    review_id) の再 insert は NoOp になる (migration 008 の UNIQUE 制約)。

Retry / Failure:
    HTTP 失敗時は exp backoff 1s,2s,4s,8s,16s で最大 5 回リトライ
    (1 初期 + 5 retries = 6 attempts)。5 回連続で retry が失敗したら
    Sentry alert を発火し、当該アプリ × country を skip して次へ進む。

CLI entry-point:
    `python -m idea_mining.fetchers.appfollow` を idea-mining-weekly
    workflow から呼ぶ。`DATABASE_URL` と `APPFOLLOW_API_TOKEN` が必須。
    `SENTRY_DSN` は任意。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg
import sentry_sdk
import yaml
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

SOURCE_NAME: Final[str] = "appfollow"

APPFOLLOW_API_BASE: Final[str] = "https://api.appfollow.io/api/v2/reviews"
USER_AGENT: Final[str] = (
    "HibiIdeaMiningBot/1.0 (+https://github.com/kazuki-0418/hibi)"
)
HTTP_TIMEOUT_SECONDS: Final[int] = 30

# AppFollow Free は直近 7 日履歴。from/to は API の必須 query。
FETCH_WINDOW_DAYS: Final[int] = 7

# 1 initial attempt + 5 retries. After all retries exhausted, Sentry alert + skip.
RETRY_DELAYS_SECONDS: Final[tuple[int, ...]] = (1, 2, 4, 8, 16)

# country → BCP-47 lang lookup. AppFollow response の locale を優先するが、
# 欠落時は country から推定する。
LANG_BY_COUNTRY: Final[dict[str, str]] = {
    "jp": "ja",
    "us": "en",
    "gb": "en",
    "ca": "en",
    "au": "en",
}


# ----------------------------------------------------------------------
# Config (sources.yaml)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AppFollowApp:
    """sources.yaml の appfollow_apps セクション 1 件分。"""

    name: str
    app_id: str
    countries: tuple[str, ...]
    enabled: bool = True


def load_appfollow_apps(sources_yaml_path: str | Path) -> list[AppFollowApp]:
    """`sources.yaml` から有効な appfollow_apps エントリを返す。

    既存 `sources:` / `apple_apps:` / `channels` / `rss` セクションには触れない。
    """
    with open(sources_yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    raw_apps = data.get("appfollow_apps") or []
    apps: list[AppFollowApp] = []
    for entry in raw_apps:
        if not entry.get("enabled", True):
            continue
        countries_raw = entry.get("country") or []
        if not isinstance(countries_raw, list) or not countries_raw:
            log.warning(
                "appfollow: skip %r — country must be a non-empty list",
                entry.get("name"),
            )
            continue
        apps.append(
            AppFollowApp(
                name=str(entry["name"]),
                app_id=str(entry["app_id"]),
                countries=tuple(str(c) for c in countries_raw),
                enabled=True,
            )
        )
    return apps


# ----------------------------------------------------------------------
# HTTP fetch with retry + backoff
# ----------------------------------------------------------------------


HttpGet = Callable[[str, dict[str, str]], dict]


def _default_http_get(url: str, headers: dict[str, str]) -> dict:
    """Default JSON GET. Raises URLError / HTTPError / JSONDecodeError / TimeoutError."""
    req = Request(url, headers=headers)
    with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        payload = resp.read()
    return json.loads(payload.decode("utf-8"))


_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    URLError,
    HTTPError,
    TimeoutError,
    json.JSONDecodeError,
    ConnectionError,
)


def _build_url(app_id: str, country: str, *, days: int = FETCH_WINDOW_DAYS) -> str:
    """AppFollow Reviews API の query string を組み立てる。

    必須 query: ext_id / from / to。ext_id はストア側 app id を渡す。
    from-to は UTC date (YYYY-MM-DD)、AppFollow Free の 7-day history と
    合わせる。country は任意だが、jp 専用運用なので必ず付ける。
    """
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=days)
    params = {
        "ext_id": app_id,
        "country": country,
        "from": since.isoformat(),
        "to": today.isoformat(),
        "page": "1",
    }
    return f"{APPFOLLOW_API_BASE}?{urlencode(params)}"


def fetch_one(
    country: str,
    app_id: str,
    *,
    api_token: str,
    http_get: HttpGet = _default_http_get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict | None:
    """Fetch 1 (country, app_id) feed with exp-backoff retry.

    Returns the decoded JSON dict on success, or ``None`` if all retries
    were exhausted. On exhaustion, sends a Sentry alert and returns
    ``None`` so the caller can skip and move on.
    """
    url = _build_url(app_id, country)
    headers = {
        "User-Agent": USER_AGENT,
        "X-AppFollow-API-Token": api_token,
        "Accept": "application/json",
    }
    last_err: BaseException | None = None

    try:
        return http_get(url, headers)
    except _RETRYABLE_EXC as e:
        last_err = e
        log.warning("appfollow: initial fetch failed for %s/%s: %r", country, app_id, e)

    for retry_n, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
        sleep_fn(delay)
        try:
            return http_get(url, headers)
        except _RETRYABLE_EXC as e:
            last_err = e
            log.warning(
                "appfollow: retry %d/%d failed for %s/%s: %r",
                retry_n,
                len(RETRY_DELAYS_SECONDS),
                country,
                app_id,
                e,
            )

    sentry_sdk.capture_message(
        f"appfollow: 5 consecutive retries exhausted for {country}/{app_id}: {last_err!r}",
        level="error",
    )
    return None


# ----------------------------------------------------------------------
# Parser (AppFollow response → voice rows)
# ----------------------------------------------------------------------


def _extract_review_list(payload: dict) -> list[dict]:
    """AppFollow response の top-level からレビュー list を defensive に取り出す。

    実 API の正確な構造はドキュメント記載なしのため、複数候補を順に試す。
    本機 token 取得後に実 response を見て不要な候補は削減する。
    """
    if not isinstance(payload, dict):
        return []

    candidates = (
        ("reviews", "list"),
        ("reviews",),
        ("data", "list"),
        ("data", "reviews"),
        ("data",),
        ("items",),
        ("results",),
    )
    for path in candidates:
        node: Any = payload
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
            if node is None:
                break
        if isinstance(node, list):
            return [e for e in node if isinstance(e, dict)]
    return []


def _parse_rating(raw: Any) -> int | None:
    """rating を int (1-5) に。失敗時 None (= 不正エントリは捨てる)。"""
    if raw is None:
        return None
    try:
        v = int(raw)
    except (ValueError, TypeError):
        return None
    if v < 1 or v > 5:
        return None
    return v


def _pick_str(entry: dict, *keys: str) -> str | None:
    """entry から最初に見つかった非空 string を返す。"""
    for key in keys:
        val = entry.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def parse_review_entries(
    payload: dict,
    *,
    country: str,
    app_id: str,
    app_name: str | None = None,
) -> list[dict]:
    """AppFollow response を voice row dict のリストに整形。★5 は除外。

    Returns:
        list of dicts with keys:
            source     — fixed 'appfollow'
            source_id  — ストア側 review_id (str)
            posted_at  — ISO timestamp (str)
            title      — review title (str | None)
            body       — review content (str | None)
            meta       — {rating, author, country, lang, app_version, app_id,
                          app_name, appfollow_id}
    """
    reviews = _extract_review_list(payload)
    if not reviews:
        return []

    default_lang = LANG_BY_COUNTRY.get(country, country)
    rows: list[dict] = []
    for entry in reviews:
        rating = _parse_rating(entry.get("rating"))
        if rating is None:
            continue
        if rating == 5:
            # ★5 は idea-mining 対象外 (positive bias / spam)。
            continue
        # ストア側 review id を安定キーに、AppFollow 内部 id は meta へ。
        review_id = _pick_str(entry, "review_id")
        if not review_id:
            # fallback: AppFollow 内部 id を source_id にする (Apple/Google
            # 側に同一レビューが届かないより、id 違いで重複しても害は薄い)。
            review_id = _pick_str(entry, "id")
        if not review_id:
            continue
        posted_at = _pick_str(entry, "dt", "date", "updated", "time", "created")
        if not posted_at:
            continue
        locale = _pick_str(entry, "locale") or default_lang
        meta: dict[str, Any] = {
            "rating": rating,
            "author": _pick_str(entry, "author", "user_name"),
            "user_id": _pick_str(entry, "user_id"),
            "country": country,
            "lang": locale,
            "app_version": _pick_str(entry, "app_version", "version"),
            "app_id": app_id,
            "app_name": app_name,
            "appfollow_id": _pick_str(entry, "id"),
            "store": _pick_str(entry, "store"),
        }
        # meta は None 値を素直に残す (psycopg は Jsonb で受ける)。
        rows.append(
            {
                "source": SOURCE_NAME,
                "source_id": review_id,
                "posted_at": posted_at,
                "title": _pick_str(entry, "title"),
                "body": _pick_str(entry, "content", "body", "text"),
                "meta": meta,
            }
        )
    return rows


# ----------------------------------------------------------------------
# DB insert
# ----------------------------------------------------------------------


INSERT_SQL: Final[str] = """
    INSERT INTO voices (source, source_id, posted_at, title, body, meta)
    VALUES (%(source)s, %(source_id)s, %(posted_at)s, %(title)s, %(body)s, %(meta)s)
    ON CONFLICT (source, source_id) DO NOTHING
"""


def insert_voices(conn: psycopg.Connection, rows: list[dict]) -> int:
    """Bulk-insert voice rows. Returns the number of rows the DB reports
    as actually inserted (ON CONFLICT skips do not count).
    """
    if not rows:
        return 0
    inserted = 0
    with conn.cursor() as cur:
        for row in rows:
            params = {
                "source": row["source"],
                "source_id": row["source_id"],
                "posted_at": row["posted_at"],
                "title": row.get("title"),
                "body": row.get("body"),
                "meta": Jsonb(row.get("meta") or {}),
            }
            cur.execute(INSERT_SQL, params)
            inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    return inserted


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------


@dataclass
class RunStats:
    apps_total: int = 0
    pairs_total: int = 0
    pairs_skipped: int = 0
    rows_parsed: int = 0
    rows_inserted: int = 0
    failures: list[str] = field(default_factory=list)


def run_once(
    apps: list[AppFollowApp],
    *,
    conn: psycopg.Connection,
    api_token: str,
    http_get: HttpGet = _default_http_get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> RunStats:
    """Drive (app × country) iteration end-to-end. Single-process, sync."""
    stats = RunStats(apps_total=len(apps))
    for app in apps:
        for country in app.countries:
            stats.pairs_total += 1
            payload = fetch_one(
                country,
                app.app_id,
                api_token=api_token,
                http_get=http_get,
                sleep_fn=sleep_fn,
            )
            if payload is None:
                stats.pairs_skipped += 1
                stats.failures.append(f"{country}/{app.app_id}")
                continue
            rows = parse_review_entries(
                payload, country=country, app_id=app.app_id, app_name=app.name
            )
            stats.rows_parsed += len(rows)
            stats.rows_inserted += insert_voices(conn, rows)
    return stats


# ----------------------------------------------------------------------
# CLI entry-point (invoked by .github/workflows/idea-mining-weekly.yml)
# ----------------------------------------------------------------------


REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES_YAML: Final[Path] = REPO_ROOT / "sources.yaml"


def _init_sentry() -> None:
    """Sentry を `observability.init_sentry_from_env` と同じ env で初期化。"""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.info("appfollow: SENTRY_DSN unset — failure alerts disabled")
        return
    sentry_sdk.init(
        dsn=dsn,
        release=os.environ.get("HIBI_RELEASE", "dev"),
        environment=os.environ.get("HIBI_ENV", "production"),
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("pipeline", "idea_mining_appfollow")


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return psycopg.connect(url)


def _require_token() -> str:
    token = os.environ.get("APPFOLLOW_API_TOKEN")
    if not token:
        print("ERROR: APPFOLLOW_API_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    return token


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _init_sentry()

    api_token = _require_token()
    apps = load_appfollow_apps(DEFAULT_SOURCES_YAML)
    log.info("appfollow: %d enabled apps loaded", len(apps))
    if not apps:
        log.info("appfollow: no enabled apps — nothing to do")
        return 0

    with _connect() as conn:
        stats = run_once(apps, conn=conn, api_token=api_token)

    log.info(
        "appfollow: done apps=%d pairs=%d skipped=%d parsed=%d inserted=%d failures=%s",
        stats.apps_total,
        stats.pairs_total,
        stats.pairs_skipped,
        stats.rows_parsed,
        stats.rows_inserted,
        stats.failures,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
