"""Idea-mining Critic — candidates → critic_verdict via Anthropic Sonnet.

Issue #139 (Epic #134) の実装。`candidates` テーブルで `critic_verdict IS NULL`
の行を Sonnet (`claude-sonnet-4-6`) で adversarial 評価し、verdict
('GO' / 'PENDING' / 'KILL') と JSONB の critic_meta を UPDATE する。

特徴:
    * Ideator (#138) の出力を後段で評価するレーン。同テーブルへの新規 INSERT
      は行わず UPDATE のみ。
    * profile/user-constraints + negative-examples を system prompt 先頭に注入
      する (`prompts._profile_block.profile_block()`)。
    * Decisions §4 の RUBRIC テキストを system prompt 末尾に verbatim 含む
      (`prompts.critic.SYSTEM_PROMPT_TEMPLATE`)。
    * 1 row 1 commit。`critic_verdict IS NULL` を snapshot し、その id 列を
      iterate するため同 batch 内で同一 row を 2 度 UPDATE しない。
    * 1 row の Sonnet 応答が malformed JSON でも他 row の UPDATE は巻き戻らない
      (raise / retry せず sentry capture + warning ログで skip)。

CLI:
    python -m idea_mining.critic

Required env:
    DATABASE_URL          — Neon (psycopg 3.x)
    ANTHROPIC_API_KEY     — Sonnet access
    OBSIDIAN_VAULT_ROOT   — profile/*.md の置かれた Vault clone

Optional env:
    SENTRY_DSN            — failure alerts (`idea_mining.critic` tag)
    HIBI_RELEASE          — sentry release
    HIBI_ENV              — sentry environment
    HIBI_VAULT_OPTIONAL=1 — profile_loader を空文字で fall through (テスト用、
                            本番では絶対 set しない)。CLI 側でも空 profile は
                            fails-closed (exit 1) として扱う。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Final

import psycopg
import sentry_sdk
from anthropic import Anthropic

from idea_mining.prompts._profile_block import profile_block
from idea_mining.prompts.critic import SYSTEM_PROMPT_TEMPLATE

log = logging.getLogger(__name__)

SONNET_MODEL: Final[str] = "claude-sonnet-4-6"
MAX_TOKENS: Final[int] = 4000

ALLOWED_VERDICTS: Final[frozenset[str]] = frozenset({"GO", "PENDING", "KILL"})

# critic_meta JSONB に必ず含める鍵。Sonnet 応答に欠落していれば JSON null として
# 保存する (downstream で .get(...) しやすいよう、空ではなく欠落鍵を null で
# 明示する方針)。
REQUIRED_META_KEYS: Final[tuple[str, ...]] = (
    "five_forces",
    "pestle",
    "kill_flags",
    "llm_moat_conditions",
    "killer_scenarios",
    "cited_competitors",
    "kill_reasons",
)

SELECT_CANDIDATE_IDS_SQL: Final[str] = """
    SELECT id
    FROM candidates
    WHERE critic_verdict IS NULL
    ORDER BY id
"""

SELECT_CANDIDATE_SQL: Final[str] = """
    SELECT id, name, one_liner, target_user, monetization,
           llm_moat_conditions, why_different, estimated_mvp_hours,
           killer_use_case
    FROM candidates
    WHERE id = %s
"""

UPDATE_CRITIC_SQL: Final[str] = """
    UPDATE candidates
    SET critic_verdict = %s,
        critic_meta = %s::jsonb
    WHERE id = %s
      AND critic_verdict IS NULL
"""


# ----------------------------------------------------------------------
# Prompt assembly
# ----------------------------------------------------------------------


def build_system_prompt(profile: str) -> str:
    """Inject the profile block at the head of the Critic system prompt.

    Raises:
        ValueError: when ``profile`` is empty. The Critic must never call
            Sonnet without user-constraints + negative-examples in the
            prompt (Issue #139 acceptance criterion).
    """
    if not profile.strip():
        raise ValueError(
            "profile_block is empty; refusing to build prompt without "
            "user-constraints + negative-examples"
        )
    return SYSTEM_PROMPT_TEMPLATE.format(profile_block=profile)


def build_user_message(candidate: dict[str, object]) -> str:
    """Render the candidate as the user-message body for Sonnet."""
    return (
        "Candidate を 1 件評価してください。\n\n"
        f"name: {candidate['name']!r}\n"
        f"one_liner: {candidate.get('one_liner')!r}\n"
        f"target_user: {candidate.get('target_user')!r}\n"
        f"monetization: {candidate.get('monetization')!r}\n"
        f"llm_moat_conditions: {candidate.get('llm_moat_conditions')!r}\n"
        f"why_different: {candidate.get('why_different')!r}\n"
        f"estimated_mvp_hours: {candidate.get('estimated_mvp_hours')!r}\n"
        f"killer_use_case: {candidate.get('killer_use_case')!r}\n\n"
        'JSON のみで {"verdict": ..., "five_forces": ..., ...} を返してください。'
    )


# ----------------------------------------------------------------------
# Sonnet call + parsing
# ----------------------------------------------------------------------


def call_sonnet(
    client: Anthropic, *, system_prompt: str, user_message: str
) -> str:
    """Call Sonnet and return the raw text response."""
    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text.strip()


def parse_sonnet_response(raw_text: str) -> dict[str, object]:
    """Parse Sonnet's JSON output into a top-level dict.

    Raises:
        ValueError: malformed JSON or non-object top-level.
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
    return parsed


def extract_verdict_and_meta(
    parsed: dict[str, object],
) -> tuple[str, dict[str, object]]:
    """Pull verdict + REQUIRED_META_KEYS out of a parsed Sonnet response.

    Returns ``(verdict, meta)``.

    Raises:
        ValueError: when ``verdict`` is missing, non-str, or not in
            ``ALLOWED_VERDICTS``.
    """
    verdict_raw = parsed.get("verdict")
    if not isinstance(verdict_raw, str):
        raise ValueError(f"verdict must be str: {verdict_raw!r}")
    verdict = verdict_raw.strip().upper()
    if verdict not in ALLOWED_VERDICTS:
        raise ValueError(f"invalid verdict: {verdict_raw!r}")
    meta: dict[str, object] = {key: parsed.get(key) for key in REQUIRED_META_KEYS}
    return verdict, meta


# ----------------------------------------------------------------------
# DB I/O
# ----------------------------------------------------------------------


def fetch_candidate_ids(conn: psycopg.Connection) -> list[int]:
    """Snapshot the ids of candidates where critic_verdict IS NULL."""
    with conn.cursor() as cur:
        cur.execute(SELECT_CANDIDATE_IDS_SQL)
        rows = cur.fetchall()
    return [int(row[0]) for row in rows]


def fetch_candidate(
    conn: psycopg.Connection, candidate_id: int
) -> dict[str, object] | None:
    """Load a single candidate row by id, or None if not present."""
    with conn.cursor() as cur:
        cur.execute(SELECT_CANDIDATE_SQL, (candidate_id,))
        row = cur.fetchone()
    if row is None:
        return None
    moat_raw = row[5]
    moat: list[str] = (
        [str(m) for m in moat_raw] if isinstance(moat_raw, list) else []
    )
    return {
        "id": int(row[0]),
        "name": row[1],
        "one_liner": row[2],
        "target_user": row[3],
        "monetization": row[4],
        "llm_moat_conditions": moat,
        "why_different": row[6],
        "estimated_mvp_hours": row[7],
        "killer_use_case": row[8],
    }


def update_critic_verdict(
    conn: psycopg.Connection,
    *,
    candidate_id: int,
    verdict: str,
    meta: dict[str, object],
) -> int:
    """UPDATE one candidate's verdict + meta, commit, return rowcount.

    Commits immediately so a downstream row failing does not roll back
    rows that already succeeded (Issue #139 D: row-level transaction).
    The ``WHERE critic_verdict IS NULL`` clause is defense-in-depth
    against double-UPDATE within the same batch.
    """
    meta_json = json.dumps(meta, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(UPDATE_CRITIC_SQL, (verdict, meta_json, candidate_id))
        rowcount = cur.rowcount
    conn.commit()
    return rowcount


# ----------------------------------------------------------------------
# Orchestration (single candidate)
# ----------------------------------------------------------------------


def run_for_candidate(
    conn: psycopg.Connection,
    client: Anthropic,
    *,
    candidate_id: int,
    profile: str,
) -> bool:
    """End-to-end: fetch → Sonnet → parse → UPDATE for one candidate.

    Returns True on UPDATE success, False on any skip (row gone, malformed
    JSON, invalid verdict). Skips never raise; they log + sentry capture.
    """
    candidate = fetch_candidate(conn, candidate_id)
    if candidate is None:
        log.warning(
            "critic: candidate not found: %d — skipping", candidate_id
        )
        sentry_sdk.capture_message(
            f"critic: candidate not found: {candidate_id}",
            level="warning",
        )
        return False

    system_prompt = build_system_prompt(profile)
    user_message = build_user_message(candidate)
    raw_text = call_sonnet(
        client, system_prompt=system_prompt, user_message=user_message
    )

    try:
        parsed = parse_sonnet_response(raw_text)
        verdict, meta = extract_verdict_and_meta(parsed)
    except ValueError as exc:
        log.warning(
            "critic: malformed Sonnet JSON for candidate %d: %s",
            candidate_id,
            exc,
        )
        sentry_sdk.capture_message(
            (
                f"critic: malformed Sonnet JSON for candidate "
                f"{candidate_id}: {exc}"
            ),
            level="warning",
        )
        return False

    rowcount = update_critic_verdict(
        conn,
        candidate_id=candidate_id,
        verdict=verdict,
        meta=meta,
    )
    log.info(
        "critic: candidate %d → verdict=%s (rowcount=%d)",
        candidate_id,
        verdict,
        rowcount,
    )
    return True


# ----------------------------------------------------------------------
# CLI entry-point
# ----------------------------------------------------------------------


def _init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.info("critic: SENTRY_DSN unset — failure alerts disabled")
        return
    sentry_sdk.init(
        dsn=dsn,
        release=os.environ.get("HIBI_RELEASE", "dev"),
        environment=os.environ.get("HIBI_ENV", "production"),
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("pipeline", "idea_mining_critic")


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return psycopg.connect(url)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _init_sentry()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1

    try:
        profile = profile_block()
    except RuntimeError as exc:
        print(f"ERROR: profile load failed: {exc}", file=sys.stderr)
        return 1
    if not profile.strip():
        print(
            "ERROR: profile is empty. Set OBSIDIAN_VAULT_ROOT and ensure "
            "profile/user-constraints.md and profile/negative-examples.md "
            "exist. (HIBI_VAULT_OPTIONAL is for tests only.)",
            file=sys.stderr,
        )
        return 1

    client = Anthropic(api_key=api_key)

    total_updated = 0
    total_skipped = 0
    with _connect() as conn:
        candidate_ids = fetch_candidate_ids(conn)
        log.info(
            "critic: %d candidate(s) to evaluate", len(candidate_ids)
        )
        for cid in candidate_ids:
            try:
                ok = run_for_candidate(
                    conn,
                    client,
                    candidate_id=cid,
                    profile=profile,
                )
            except Exception as exc:  # noqa: BLE001 — per-row fence
                log.exception("critic: candidate %d failed: %s", cid, exc)
                sentry_sdk.capture_exception(exc)
                total_skipped += 1
                continue
            if ok:
                total_updated += 1
            else:
                total_skipped += 1

    log.info(
        "critic: done. updated=%d skipped=%d total=%d",
        total_updated,
        total_skipped,
        len(candidate_ids),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
