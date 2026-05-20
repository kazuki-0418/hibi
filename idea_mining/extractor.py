"""Idea-mining extractor — voices → patterns via Haiku.

直近 7 日の `voices` (Apple iTunes ★1-4 customer reviews 等) を読み、
Haiku でクラスタリングして構造的ペインを `patterns` テーブルに UPSERT
する週 3 回 (火 / 木 / 土 03:00 UTC) cron バッチ。

newspaper pipeline (`daily_news.py` / `articles` / ranking / mailer /
archive) からは独立した経路。失敗してもニュースレターには影響しない。

Idempotency:
    INSERT は `ON CONFLICT (week_iso, pain) DO UPDATE` で、同一 (週, pain)
    が既にあれば frequency / source_diversity / representative_voices /
    confidence / categories / meta / updated_at を refresh する。古い週の
    row は削除しない (歴史記録として残す)。

Failure modes:
    Haiku が malformed JSON を返した場合は sentry_sdk.capture_message +
    log.warning を発火し、insert ゼロのまま exit 0 で終わる (raise しない、
    自動 retry もしない)。voices が 0 件 / Apple のみでも exit 0。

CLI entry-point:
    `python -m idea_mining.extractor` を idea-mining-extractor workflow
    から呼ぶ。`DATABASE_URL` と `ANTHROPIC_API_KEY` が必須。`SENTRY_DSN`
    は任意。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

import psycopg
import sentry_sdk
from anthropic import Anthropic
from psycopg.types.json import Jsonb

from idea_mining.prompts.extractor import SYSTEM_PROMPT

log = logging.getLogger(__name__)

CLAUDE_MODEL: Final[str] = "claude-haiku-4-5-20251001"
MAX_TOKENS: Final[int] = 2000
MIN_FREQUENCY: Final[int] = 3
LOW_DIVERSITY_THRESHOLD: Final[int] = 2
LOW_DIVERSITY_CONFIDENCE_CAP: Final[float] = 0.5

SELECT_RECENT_VOICES_SQL: Final[str] = """
    SELECT id, source, posted_at, title, body, meta
    FROM voices
    WHERE posted_at >= NOW() - INTERVAL '7 days'
    ORDER BY posted_at ASC
"""

UPSERT_PATTERN_SQL: Final[str] = """
    INSERT INTO patterns (
        week_iso, pain, categories, frequency, source_diversity,
        representative_voices, confidence, meta
    )
    VALUES (
        %(week_iso)s, %(pain)s, %(categories)s, %(frequency)s,
        %(source_diversity)s, %(representative_voices)s::uuid[],
        %(confidence)s, %(meta)s
    )
    ON CONFLICT (week_iso, pain) DO UPDATE SET
        categories = EXCLUDED.categories,
        frequency = EXCLUDED.frequency,
        source_diversity = EXCLUDED.source_diversity,
        representative_voices = EXCLUDED.representative_voices,
        confidence = EXCLUDED.confidence,
        meta = EXCLUDED.meta,
        updated_at = now()
"""


# ----------------------------------------------------------------------
# Week ISO
# ----------------------------------------------------------------------


def current_week_iso(now: datetime | None = None) -> str:
    """Return ISO week as `YYYY-Www` (zero-padded week)."""
    if now is None:
        now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


# ----------------------------------------------------------------------
# Voices fetch
# ----------------------------------------------------------------------


def fetch_recent_voices(conn: psycopg.Connection) -> list[dict[str, object]]:
    """Return all `voices` rows with posted_at within the last 7 days."""
    with conn.cursor() as cur:
        cur.execute(SELECT_RECENT_VOICES_SQL)
        rows = cur.fetchall()
    out: list[dict[str, object]] = []
    for row in rows:
        voice_id, source, posted_at, title, body, meta = row
        rating: int | None = None
        if isinstance(meta, dict):
            raw_rating = meta.get("rating")
            if isinstance(raw_rating, int):
                rating = raw_rating
        out.append(
            {
                "id": str(voice_id),
                "source": source,
                "posted_at": posted_at.isoformat() if posted_at else None,
                "title": title,
                "body": body,
                "rating": rating,
            }
        )
    return out


# ----------------------------------------------------------------------
# Haiku call + parsing
# ----------------------------------------------------------------------


def build_user_message(voices: list[dict[str, object]]) -> str:
    """Render the voice list as the user-message body for Haiku."""
    payload = {"voices": voices}
    return (
        "以下は直近 7 日の `voices` の一覧 (JSON) です。"
        " SYSTEM で指示された JSON スキーマで `patterns` を返してください。\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def call_haiku(
    client: Anthropic, voices: list[dict[str, object]]
) -> str:
    """Call Haiku and return the raw text response."""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(voices)}],
    )
    return response.content[0].text.strip()


def _is_valid_uuid(candidate: object) -> bool:
    if not isinstance(candidate, str):
        return False
    try:
        UUID(candidate)
    except ValueError:
        return False
    return True


def parse_haiku_response(
    raw_text: str, *, voice_ids: set[str]
) -> list[dict[str, object]]:
    """Parse Haiku's JSON output into a normalized list of pattern dicts.

    Raises:
        ValueError: malformed JSON, wrong shape, or any required field
            missing/wrong-typed. Caller is expected to handle and exit 0.

    Returns:
        Validated pattern dicts. Caller still has to apply the
        `frequency >= 3` filter and the low-diversity confidence clamp.
    """
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object in response: {raw_text!r}")

    try:
        parsed = json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON decode failed: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"top-level JSON is not an object: {parsed!r}")
    patterns_raw = parsed.get("patterns")
    if not isinstance(patterns_raw, list):
        raise ValueError(f"`patterns` must be a list: {patterns_raw!r}")

    out: list[dict[str, object]] = []
    for i, p in enumerate(patterns_raw):
        if not isinstance(p, dict):
            raise ValueError(f"pattern[{i}] not an object: {p!r}")
        pain = p.get("pain")
        if not isinstance(pain, str) or not pain.strip():
            raise ValueError(f"pattern[{i}].pain missing/empty: {p!r}")
        categories_raw = p.get("categories", [])
        if not isinstance(categories_raw, list) or not all(
            isinstance(c, str) for c in categories_raw
        ):
            raise ValueError(
                f"pattern[{i}].categories must be a list[str]: {categories_raw!r}"
            )
        frequency = p.get("frequency")
        if not isinstance(frequency, int) or frequency < 0:
            raise ValueError(
                f"pattern[{i}].frequency must be a non-negative int: {frequency!r}"
            )
        source_diversity = p.get("source_diversity")
        if not isinstance(source_diversity, int) or source_diversity < 0:
            raise ValueError(
                f"pattern[{i}].source_diversity must be a non-negative int:"
                f" {source_diversity!r}"
            )
        rep_voices_raw = p.get("representative_voices", [])
        if not isinstance(rep_voices_raw, list) or not all(
            _is_valid_uuid(v) for v in rep_voices_raw
        ):
            raise ValueError(
                f"pattern[{i}].representative_voices must be a list[uuid]:"
                f" {rep_voices_raw!r}"
            )
        confidence_raw = p.get("confidence")
        if not isinstance(confidence_raw, (int, float)):
            raise ValueError(
                f"pattern[{i}].confidence must be a number: {confidence_raw!r}"
            )
        confidence = float(confidence_raw)
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError(
                f"pattern[{i}].confidence out of [0, 1]: {confidence!r}"
            )
        rep_voices = [v for v in rep_voices_raw if v in voice_ids]
        out.append(
            {
                "pain": pain.strip(),
                "categories": list(categories_raw),
                "frequency": frequency,
                "source_diversity": source_diversity,
                "representative_voices": rep_voices,
                "confidence": confidence,
            }
        )
    return out


# ----------------------------------------------------------------------
# Filtering + clamping
# ----------------------------------------------------------------------


def filter_and_clamp(
    patterns: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Drop frequency < 3 and clamp confidence when source_diversity < 2."""
    out: list[dict[str, object]] = []
    for p in patterns:
        frequency = p["frequency"]
        source_diversity = p["source_diversity"]
        assert isinstance(frequency, int)
        assert isinstance(source_diversity, int)
        if frequency < MIN_FREQUENCY:
            continue
        confidence = p["confidence"]
        assert isinstance(confidence, float)
        if source_diversity < LOW_DIVERSITY_THRESHOLD:
            confidence = min(confidence, LOW_DIVERSITY_CONFIDENCE_CAP)
        out.append({**p, "confidence": confidence})
    return out


# ----------------------------------------------------------------------
# UPSERT
# ----------------------------------------------------------------------


def upsert_patterns(
    conn: psycopg.Connection,
    patterns: list[dict[str, object]],
    *,
    week_iso: str,
    raw_response_snippet: str,
) -> int:
    """UPSERT pattern rows. Returns the number of rows touched (insert or update)."""
    if not patterns:
        return 0
    affected = 0
    with conn.cursor() as cur:
        for p in patterns:
            params = {
                "week_iso": week_iso,
                "pain": p["pain"],
                "categories": list(p["categories"]),  # type: ignore[arg-type]
                "frequency": p["frequency"],
                "source_diversity": p["source_diversity"],
                "representative_voices": list(p["representative_voices"]),  # type: ignore[arg-type]
                "confidence": p["confidence"],
                "meta": Jsonb(
                    {
                        "model": CLAUDE_MODEL,
                        "raw_response_snippet": raw_response_snippet[:500],
                    }
                ),
            }
            cur.execute(UPSERT_PATTERN_SQL, params)
            affected += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    return affected


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------


def run_once(
    conn: psycopg.Connection,
    client: Anthropic,
    *,
    week_iso: str,
) -> int:
    """End-to-end one-shot extraction. Returns rows upserted (0 on any soft fail)."""
    voices = fetch_recent_voices(conn)
    log.info("extractor: %d voices in last 7 days", len(voices))
    if not voices:
        log.info("extractor: no voices — nothing to do")
        return 0

    raw_text = call_haiku(client, voices)
    voice_ids = {str(v["id"]) for v in voices}
    try:
        parsed = parse_haiku_response(raw_text, voice_ids=voice_ids)
    except ValueError as exc:
        log.warning("extractor: malformed Haiku response: %s", exc)
        sentry_sdk.capture_message(
            f"extractor: malformed Haiku JSON response: {exc}",
            level="warning",
        )
        return 0

    filtered = filter_and_clamp(parsed)
    log.info(
        "extractor: Haiku returned %d patterns, %d after frequency/diversity filter",
        len(parsed),
        len(filtered),
    )
    if not filtered:
        return 0
    return upsert_patterns(
        conn, filtered, week_iso=week_iso, raw_response_snippet=raw_text
    )


# ----------------------------------------------------------------------
# CLI entry-point
# ----------------------------------------------------------------------


def _init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.info("extractor: SENTRY_DSN unset — failure alerts disabled")
        return
    sentry_sdk.init(
        dsn=dsn,
        release=os.environ.get("HIBI_RELEASE", "dev"),
        environment=os.environ.get("HIBI_ENV", "production"),
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("pipeline", "idea_mining_extractor")


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

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        sys.exit(1)
    client = Anthropic(api_key=api_key)
    week_iso = current_week_iso()
    log.info("extractor: week_iso=%s", week_iso)

    with _connect() as conn:
        upserted = run_once(conn, client, week_iso=week_iso)

    log.info("extractor: done week_iso=%s upserted=%d", week_iso, upserted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
