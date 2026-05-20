"""Apple iTunes RSS fetcher — ★1-4 customer reviews into `voices`.

各 (country, app_id) について Apple 公式 RSS customer-reviews endpoint を
叩き、★1-4 のレビューだけを `voices` テーブルに insert する。★5 は
INSERT 前に除外し、元の rating は `meta.rating` (1-5) に保持する。

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
    `python -m idea_mining.fetchers.apple_rss` を idea-mining-weekly
    workflow から呼ぶ。`DATABASE_URL` 必須。`SENTRY_DSN` は任意。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
import sentry_sdk
import yaml
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

SOURCE_NAME: Final[str] = "apple_rss"

APPLE_RSS_URL_FMT: Final[str] = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "id={app_id}/sortby=mostrecent/json"
)
USER_AGENT: Final[str] = (
    "HibiIdeaMiningBot/1.0 (+https://github.com/kazuki-0418/hibi)"
)
HTTP_TIMEOUT_SECONDS: Final[int] = 30

# 1 initial attempt + 5 retries with these inter-attempt delays.
# After all retries are exhausted (5 consecutive failures), Sentry alert + skip.
RETRY_DELAYS_SECONDS: Final[tuple[int, ...]] = (1, 2, 4, 8, 16)

# country → BCP-47 lang lookup. Apple feed の本文は country の主要言語に
# 倣う前提 (本文判定は行わない)。MVP では jp のみ運用。
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
class AppleApp:
    """sources.yaml の apple_apps セクション 1 件分。"""

    name: str
    app_id: str
    countries: tuple[str, ...]
    enabled: bool = True


def load_apple_apps(sources_yaml_path: str | Path) -> list[AppleApp]:
    """`sources.yaml` から有効な apple_apps エントリを返す。

    既存 `sources:` / `channels` / `rss` セクションには触れない。
    """
    with open(sources_yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    raw_apps = data.get("apple_apps") or []
    apps: list[AppleApp] = []
    for entry in raw_apps:
        if not entry.get("enabled", True):
            continue
        countries_raw = entry.get("country") or []
        if not isinstance(countries_raw, list) or not countries_raw:
            log.warning(
                "apple_rss: skip %r — country must be a non-empty list",
                entry.get("name"),
            )
            continue
        apps.append(
            AppleApp(
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


HttpGet = Callable[[str], dict]


def _default_http_get(url: str) -> dict:
    """Default JSON GET. Raises URLError / HTTPError / JSONDecodeError / TimeoutError."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
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


def fetch_one(
    country: str,
    app_id: str,
    *,
    http_get: HttpGet = _default_http_get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict | None:
    """Fetch 1 (country, app_id) feed with exp-backoff retry.

    Returns the decoded JSON dict on success, or ``None`` if all retries
    were exhausted. On exhaustion, sends a Sentry alert and returns
    ``None`` so the caller can skip and move on.
    """
    url = APPLE_RSS_URL_FMT.format(country=country, app_id=app_id)
    last_err: BaseException | None = None

    try:
        return http_get(url)
    except _RETRYABLE_EXC as e:
        last_err = e
        log.warning("apple_rss: initial fetch failed for %s/%s: %r", country, app_id, e)

    for retry_n, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
        sleep_fn(delay)
        try:
            return http_get(url)
        except _RETRYABLE_EXC as e:
            last_err = e
            log.warning(
                "apple_rss: retry %d/%d failed for %s/%s: %r",
                retry_n,
                len(RETRY_DELAYS_SECONDS),
                country,
                app_id,
                e,
            )

    sentry_sdk.capture_message(
        f"apple_rss: 5 consecutive retries exhausted for {country}/{app_id}: {last_err!r}",
        level="error",
    )
    return None


# ----------------------------------------------------------------------
# Parser (Apple RSS JSON → voice rows)
# ----------------------------------------------------------------------


def _entry_field(entry: dict, key: str) -> str | None:
    """Apple feed の `{label: ...}` 構造を 1 段剥がす。欠落時 None."""
    node = entry.get(key)
    if not isinstance(node, dict):
        return None
    label = node.get("label")
    return str(label) if label is not None else None


def _entry_author(entry: dict) -> str | None:
    author = entry.get("author")
    if not isinstance(author, dict):
        return None
    name = author.get("name")
    if isinstance(name, dict):
        label = name.get("label")
        return str(label) if label is not None else None
    return None


def _parse_rating(raw: str | None) -> int | None:
    """`im:rating.label` を int に。失敗時 None (= 不正エントリは捨てる)。"""
    if raw is None:
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    if v < 1 or v > 5:
        return None
    return v


def parse_review_entries(
    payload: dict,
    *,
    country: str,
    app_id: str,
) -> list[dict]:
    """Apple RSS JSON を voice row dict のリストに整形。★5 は除外。

    Returns:
        list of dicts with keys:
            source     — fixed 'apple_rss'
            source_id  — review id (str)
            posted_at  — ISO timestamp (str)
            title      — review title (str | None)
            body       — review content (str | None)
            meta       — {version, author, country, lang, rating}
    """
    feed = payload.get("feed") or {}
    entries_raw = feed.get("entry")
    if entries_raw is None:
        return []
    if isinstance(entries_raw, dict):
        entries_raw = [entries_raw]
    if not isinstance(entries_raw, list):
        return []

    lang = LANG_BY_COUNTRY.get(country, country)
    rows: list[dict] = []
    for entry in entries_raw:
        if not isinstance(entry, dict):
            continue
        rating = _parse_rating(_entry_field(entry, "im:rating"))
        if rating is None:
            # No rating → app metadata entry or malformed; skip.
            continue
        if rating == 5:
            # ★5 は idea-mining 対象外 (positive bias / spam)。
            continue
        review_id = _entry_field(entry, "id")
        if not review_id:
            continue
        posted_at = _entry_field(entry, "updated")
        if not posted_at:
            continue
        rows.append(
            {
                "source": SOURCE_NAME,
                "source_id": review_id,
                "posted_at": posted_at,
                "title": _entry_field(entry, "title"),
                "body": _entry_field(entry, "content"),
                "meta": {
                    "version": _entry_field(entry, "im:version"),
                    "author": _entry_author(entry),
                    "country": country,
                    "lang": lang,
                    "rating": rating,
                    "app_id": app_id,
                },
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
    apps: list[AppleApp],
    *,
    conn: psycopg.Connection,
    http_get: HttpGet = _default_http_get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> RunStats:
    """Drive (app × country) iteration end-to-end. Single-process, sync."""
    stats = RunStats(apps_total=len(apps))
    for app in apps:
        for country in app.countries:
            stats.pairs_total += 1
            payload = fetch_one(
                country, app.app_id, http_get=http_get, sleep_fn=sleep_fn
            )
            if payload is None:
                stats.pairs_skipped += 1
                stats.failures.append(f"{country}/{app.app_id}")
                continue
            rows = parse_review_entries(
                payload, country=country, app_id=app.app_id
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
        log.info("apple_rss: SENTRY_DSN unset — failure alerts disabled")
        return
    sentry_sdk.init(
        dsn=dsn,
        release=os.environ.get("HIBI_RELEASE", "dev"),
        environment=os.environ.get("HIBI_ENV", "production"),
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("pipeline", "idea_mining_apple_rss")


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return psycopg.connect(url)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _init_sentry()

    apps = load_apple_apps(DEFAULT_SOURCES_YAML)
    log.info("apple_rss: %d enabled apps loaded", len(apps))
    if not apps:
        log.info("apple_rss: no enabled apps — nothing to do")
        return 0

    with _connect() as conn:
        stats = run_once(apps, conn=conn)

    log.info(
        "apple_rss: done apps=%d pairs=%d skipped=%d parsed=%d inserted=%d failures=%s",
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
