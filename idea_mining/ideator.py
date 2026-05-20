"""Idea-mining Ideator — patterns → candidates via Anthropic Opus.

Issue #138 (Epic #134) の実装。手動指定された patterns 1-3 件を入力に
Anthropic Opus (`claude-opus-4-7`) で 5-10 件の事業候補を生成し、
profile/user-constraints + profile/negative-examples を system prompt の
先頭に必ず注入したうえで、validation を通過した候補だけを `candidates`
テーブルへ INSERT する。

CLI:
    python -m idea_mining.ideator --pattern-id <uuid> [--pattern-id <uuid> ...]

最大 3 件まで `--pattern-id` を repeat 可能 (Issue 受入: 1-3 pattern)。

Required env:
    DATABASE_URL          — Neon (psycopg 3.x)
    ANTHROPIC_API_KEY     — Opus access
    OBSIDIAN_VAULT_ROOT   — profile/*.md の置かれた Vault clone

Optional env:
    SENTRY_DSN            — failure alerts (`idea_mining.ideator` tag)
    HIBI_RELEASE          — sentry release
    HIBI_ENV              — sentry environment
    HIBI_VAULT_OPTIONAL=1 — profile_loader を空文字で fall through (テスト用、
                            本番では絶対 set しない)。CLI 側でも空 profile は
                            fails-closed (exit 1) として扱う。

Fails-closed semantics:
    - profile が空 / 未整備の場合は実行を中断する (Issue 制約)。
    - patterns(id) 未取得の場合は当該 pattern を skip し、log + Sentry に残す。
    - Opus が malformed JSON を返した場合は当該 pattern を 0 件で記録し、
      他 pattern の処理は継続する (raise しない)。

Critic Agent (Issue #139) は本 Issue では呼ばない。`critic_verdict` /
`critic_meta` は NULL のまま。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Final
from uuid import UUID

import psycopg
import sentry_sdk
from anthropic import Anthropic

from idea_mining.profile_loader import load as load_profile
from idea_mining.prompts.ideator import SYSTEM_PROMPT_TEMPLATE

log = logging.getLogger(__name__)

CLAUDE_MODEL: Final[str] = "claude-opus-4-7"
MAX_TOKENS: Final[int] = 4000
MAX_PATTERNS_PER_RUN: Final[int] = 3
MIN_CANDIDATES_PER_PATTERN: Final[int] = 5
MAX_CANDIDATES_PER_PATTERN: Final[int] = 10

ALLOWED_MONETIZATION: Final[frozenset[str]] = frozenset(
    {"subscription", "one-time", "affiliate", "freemium", "b2b"}
)
ALLOWED_LLM_MOAT_CONDITIONS: Final[frozenset[str]] = frozenset(
    {
        "workflow",
        "data",
        "distribution",
        "trust",
        "network",
        "physical",
        "regulatory",
    }
)

SELECT_PATTERN_SQL: Final[str] = """
    SELECT id, pain
    FROM patterns
    WHERE id = %s
"""

INSERT_CANDIDATE_SQL: Final[str] = """
    INSERT INTO candidates (
        spot_id, pattern_id, name, one_liner, target_user, monetization,
        llm_moat_conditions, why_different, estimated_mvp_hours,
        killer_use_case
    ) VALUES (
        %(spot_id)s, %(pattern_id)s, %(name)s, %(one_liner)s,
        %(target_user)s, %(monetization)s, %(llm_moat_conditions)s,
        %(why_different)s, %(estimated_mvp_hours)s, %(killer_use_case)s
    )
"""


# ----------------------------------------------------------------------
# Profile / prompt assembly
# ----------------------------------------------------------------------


def build_system_prompt(profile_block: str) -> str:
    """Inject the profile block at the head of the system prompt.

    Raises:
        ValueError: when ``profile_block`` is empty. The Ideator must
            never call Opus without user-constraints + negative-examples
            in the prompt (Issue #138 acceptance criterion).
    """
    if not profile_block.strip():
        raise ValueError(
            "profile_block is empty; refusing to build prompt without "
            "user-constraints + negative-examples"
        )
    return SYSTEM_PROMPT_TEMPLATE.format(profile_block=profile_block)


def build_user_message(pattern: dict[str, object]) -> str:
    """Render the pattern as the user-message body for Opus."""
    pain = pattern["pain"]
    assert isinstance(pain, str)
    return (
        "Pattern を 1 件処理してください。\n\n"
        f"pattern.pain: {pain}\n\n"
        'JSON のみで {"candidates": [...]} を返してください。'
    )


def extract_negative_example_names(profile_markdown: str) -> list[str]:
    """Pull H2 headings under any '# Negative Examples'-like H1 section.

    `profile/negative-examples.md` is concatenated into the loader output
    after `user-constraints.md`, so we scan for an H1 whose text contains
    'negative' or the Japanese 'ネガティブ', and harvest the immediately
    following '## ' headings. Used as an insert-time guard against the
    Ideator emitting candidates that lexically match KILLed concepts
    (e.g. 'Aesthetic OS').
    """
    names: list[str] = []
    in_negative_section = False
    for raw_line in profile_markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            header = line[2:].strip().lower()
            in_negative_section = (
                "negative" in header or "ネガティブ" in header
            )
            continue
        if in_negative_section and line.startswith("## "):
            name = line[3:].strip()
            if name:
                names.append(name)
    return names


def _matches_negative_example(
    candidate: dict[str, object], forbidden: list[str]
) -> str | None:
    """Return the forbidden name that matches, or None.

    Case-insensitive substring match against the candidate's ``name`` and
    ``one_liner``. Intentionally crude — the prompt is the primary defense;
    this is just a final cheap gate for slip-throughs.
    """
    haystacks: list[str] = []
    for field in ("name", "one_liner"):
        value = candidate.get(field)
        if isinstance(value, str):
            haystacks.append(value.lower())
    for forbidden_name in forbidden:
        needle = forbidden_name.strip().lower()
        if not needle:
            continue
        for hay in haystacks:
            if needle in hay:
                return forbidden_name
    return None


# ----------------------------------------------------------------------
# Opus call + JSON parsing
# ----------------------------------------------------------------------


def call_opus(
    client: Anthropic, *, system_prompt: str, user_message: str
) -> str:
    """Call Opus and return the raw text response."""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text.strip()


def parse_opus_response(raw_text: str) -> list[dict[str, object]]:
    """Parse Opus' JSON output into a raw list of candidate dicts.

    Field-level validation is NOT done here — see :func:`validate_candidate`.

    Raises:
        ValueError: malformed JSON, wrong top-level shape, or
            ``candidates`` not a list.
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
    candidates_raw = parsed.get("candidates")
    if not isinstance(candidates_raw, list):
        raise ValueError(
            f"`candidates` must be a list: {candidates_raw!r}"
        )

    out: list[dict[str, object]] = []
    for i, c in enumerate(candidates_raw):
        if not isinstance(c, dict):
            raise ValueError(f"candidate[{i}] not an object: {c!r}")
        out.append(c)
    return out


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


def validate_candidate(
    raw: dict[str, object],
    *,
    negative_names: list[str],
) -> tuple[dict[str, object] | None, str | None]:
    """Validate a single candidate dict.

    Returns ``(validated_candidate, None)`` on success or
    ``(None, reject_reason)`` on failure. The caller logs the reason and
    drops the row (Issue #138: skip + log, do NOT raise).

    Enforced rules (per Issue #138 acceptance criteria):

    - ``name`` is a non-empty str.
    - ``monetization`` is in {subscription, one-time, affiliate, freemium, b2b}.
    - ``llm_moat_conditions`` is a non-empty list[str], every element in
      {workflow, data, distribution, trust, network, physical, regulatory}.
    - Optional string fields (``one_liner``, ``target_user``,
      ``why_different``, ``killer_use_case``) are str-or-null.
    - ``estimated_mvp_hours`` is int-or-null.
    - ``name`` / ``one_liner`` do NOT match any item in ``negative_names``
      (case-insensitive substring match).
    """
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "missing or empty name"

    monetization = raw.get("monetization")
    if (
        not isinstance(monetization, str)
        or monetization not in ALLOWED_MONETIZATION
    ):
        return None, f"invalid monetization: {monetization!r}"

    moat_raw = raw.get("llm_moat_conditions")
    if not isinstance(moat_raw, list) or len(moat_raw) == 0:
        return None, "llm_moat_conditions empty or missing"
    moat: list[str] = []
    for m in moat_raw:
        if not isinstance(m, str):
            return None, f"non-str moat condition: {m!r}"
        normalized = m.strip().lower()
        if normalized not in ALLOWED_LLM_MOAT_CONDITIONS:
            return None, f"invalid moat condition: {m!r}"
        moat.append(normalized)

    one_liner = raw.get("one_liner")
    target_user = raw.get("target_user")
    why_different = raw.get("why_different")
    killer_use_case = raw.get("killer_use_case")
    for field_name, val in (
        ("one_liner", one_liner),
        ("target_user", target_user),
        ("why_different", why_different),
        ("killer_use_case", killer_use_case),
    ):
        if val is not None and not isinstance(val, str):
            return None, f"{field_name} must be str or null: {val!r}"

    estimated_mvp_hours = raw.get("estimated_mvp_hours")
    if estimated_mvp_hours is not None and not isinstance(
        estimated_mvp_hours, int
    ):
        return None, (
            f"estimated_mvp_hours must be int or null: {estimated_mvp_hours!r}"
        )

    hit = _matches_negative_example(
        {"name": name, "one_liner": one_liner}, negative_names
    )
    if hit is not None:
        return None, f"matches negative-example: {hit!r}"

    return (
        {
            "name": name.strip(),
            "one_liner": one_liner,
            "target_user": target_user,
            "monetization": monetization,
            "llm_moat_conditions": moat,
            "why_different": why_different,
            "estimated_mvp_hours": estimated_mvp_hours,
            "killer_use_case": killer_use_case,
        },
        None,
    )


# ----------------------------------------------------------------------
# DB I/O
# ----------------------------------------------------------------------


def fetch_pattern(
    conn: psycopg.Connection, pattern_id: str
) -> dict[str, object] | None:
    """Return ``{id, pain}`` for the given patterns(id), or None."""
    with conn.cursor() as cur:
        cur.execute(SELECT_PATTERN_SQL, (pattern_id,))
        row = cur.fetchone()
    if not row:
        return None
    pid, pain = row
    return {"id": str(pid), "pain": pain}


def insert_candidates(
    conn: psycopg.Connection,
    candidates: list[dict[str, object]],
    *,
    pattern_id: str,
) -> int:
    """INSERT each validated candidate. Returns the row count actually written."""
    if not candidates:
        return 0
    inserted = 0
    with conn.cursor() as cur:
        for c in candidates:
            params = {
                "spot_id": None,
                "pattern_id": pattern_id,
                "name": c["name"],
                "one_liner": c.get("one_liner"),
                "target_user": c.get("target_user"),
                "monetization": c["monetization"],
                "llm_moat_conditions": list(c["llm_moat_conditions"]),  # type: ignore[arg-type]
                "why_different": c.get("why_different"),
                "estimated_mvp_hours": c.get("estimated_mvp_hours"),
                "killer_use_case": c.get("killer_use_case"),
            }
            cur.execute(INSERT_CANDIDATE_SQL, params)
            inserted += 1
    conn.commit()
    return inserted


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------


def run_for_pattern(
    conn: psycopg.Connection,
    client: Anthropic,
    *,
    pattern_id: str,
    profile_block: str,
) -> int:
    """End-to-end: fetch pattern → Opus → validate → insert. Returns rows inserted."""
    pattern = fetch_pattern(conn, pattern_id)
    if pattern is None:
        log.warning("ideator: pattern not found: %s — skipping", pattern_id)
        sentry_sdk.capture_message(
            f"ideator: pattern not found: {pattern_id}",
            level="warning",
        )
        return 0

    log.info(
        "ideator: pattern_id=%s pain=%r", pattern_id, pattern["pain"]
    )

    negative_names = extract_negative_example_names(profile_block)
    log.info(
        "ideator: negative-example name guards: %d entries", len(negative_names)
    )

    system_prompt = build_system_prompt(profile_block)
    user_message = build_user_message(pattern)
    raw_text = call_opus(
        client, system_prompt=system_prompt, user_message=user_message
    )

    try:
        raw_candidates = parse_opus_response(raw_text)
    except ValueError as exc:
        log.warning(
            "ideator: malformed Opus JSON for pattern %s: %s",
            pattern_id,
            exc,
        )
        sentry_sdk.capture_message(
            f"ideator: malformed Opus JSON for pattern {pattern_id}: {exc}",
            level="warning",
        )
        return 0

    log.info(
        "ideator: Opus returned %d raw candidates for pattern %s",
        len(raw_candidates),
        pattern_id,
    )

    validated: list[dict[str, object]] = []
    rejected = 0
    for i, c in enumerate(raw_candidates):
        v, reason = validate_candidate(c, negative_names=negative_names)
        if v is None:
            rejected += 1
            log.info(
                "ideator: rejected candidate[%d] (pattern %s): %s",
                i,
                pattern_id,
                reason,
            )
            continue
        validated.append(v)

    log.info(
        "ideator: pattern %s — %d accepted, %d rejected",
        pattern_id,
        len(validated),
        rejected,
    )

    if not validated:
        return 0
    return insert_candidates(conn, validated, pattern_id=pattern_id)


# ----------------------------------------------------------------------
# CLI entry-point
# ----------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="idea_mining.ideator",
        description=(
            "B-Mode Ideator: 1-3 patterns を入力に Opus が候補を生成し "
            "candidates テーブルへ insert する。"
        ),
    )
    parser.add_argument(
        "--pattern-id",
        action="append",
        required=True,
        metavar="UUID",
        help="patterns.id (UUID). 最大 3 件まで repeat 可能。",
    )
    return parser.parse_args(argv)


def _validate_pattern_ids(raw_ids: list[str]) -> list[str]:
    if len(raw_ids) > MAX_PATTERNS_PER_RUN:
        raise ValueError(
            f"--pattern-id は最大 {MAX_PATTERNS_PER_RUN} 件まで "
            f"(received {len(raw_ids)})"
        )
    out: list[str] = []
    for pid in raw_ids:
        try:
            UUID(pid)
        except ValueError as exc:
            raise ValueError(
                f"--pattern-id is not a valid UUID: {pid!r}"
            ) from exc
        out.append(pid)
    return out


def _init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        log.info("ideator: SENTRY_DSN unset — failure alerts disabled")
        return
    sentry_sdk.init(
        dsn=dsn,
        release=os.environ.get("HIBI_RELEASE", "dev"),
        environment=os.environ.get("HIBI_ENV", "production"),
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("pipeline", "idea_mining_ideator")


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

    args = _parse_args(argv)
    try:
        pattern_ids = _validate_pattern_ids(args.pattern_id)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1

    try:
        profile_block = load_profile()
    except RuntimeError as exc:
        print(f"ERROR: profile load failed: {exc}", file=sys.stderr)
        return 1
    if not profile_block.strip():
        print(
            "ERROR: profile is empty. Set OBSIDIAN_VAULT_ROOT and ensure "
            "profile/user-constraints.md and profile/negative-examples.md "
            "exist. (HIBI_VAULT_OPTIONAL is for tests only.)",
            file=sys.stderr,
        )
        return 1

    client = Anthropic(api_key=api_key)

    total_inserted = 0
    with _connect() as conn:
        for pid in pattern_ids:
            try:
                inserted = run_for_pattern(
                    conn,
                    client,
                    pattern_id=pid,
                    profile_block=profile_block,
                )
            except Exception as exc:  # noqa: BLE001 — per-pattern fence
                log.exception("ideator: pattern %s failed: %s", pid, exc)
                sentry_sdk.capture_exception(exc)
                continue
            total_inserted += inserted

    log.info(
        "ideator: done. patterns=%d total_candidates_inserted=%d",
        len(pattern_ids),
        total_inserted,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
