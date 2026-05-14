from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol

from ._subprocess import CommandTimeout, run
from .limits import NETWORK_BACKOFF_SECONDS, SUBAGENT_TIMEOUT_SECONDS

_ENV_DENYLIST_PREFIXES: tuple[str, ...] = ("ANTHROPIC_",)


def sanitized_env() -> dict[str, str]:
    """Parent env minus any `ANTHROPIC_*` keys.

    The Manager's RealSubagent uses Claude Code OAuth (Max plan via macOS
    keychain). If `ANTHROPIC_API_KEY` ever leaks into the spawned `claude -p`
    env (e.g. via `.env` auto-discovery, a parent harness, or a hook), the
    inner subagent silently switches to API key billing. Stripping the
    `ANTHROPIC_*` namespace defends against that.
    """
    return {
        k: v for k, v in os.environ.items()
        if not any(k.startswith(p) for p in _ENV_DENYLIST_PREFIXES)
    }

_TRANSIENT_STDERR_RE = re.compile(
    r"rate.?limit|429|503|504|temporarily unavailable|connection reset|"
    r"socket hang up|ETIMEDOUT|ECONNRESET|Anthropic.{0,40}overloaded",
    re.IGNORECASE,
)


def is_transient_failure(exit_code: int, stderr: str) -> bool:
    if exit_code == 0:
        return False
    return bool(_TRANSIENT_STDERR_RE.search(stderr))


@dataclass(frozen=True)
class SubagentResult:
    exit_code: int
    raw_stdout: str
    raw_stderr: str
    cost_usd: float
    session_id: str


class Subagent(Protocol):
    def invoke(self, slash: str, args_text: str, budget_usd: float) -> SubagentResult: ...


class DummySubagent:
    """Returns scripted responses keyed by slash command. Used by tests."""

    def __init__(self, scripted: dict[str, list[SubagentResult]]) -> None:
        self._scripted: dict[str, list[SubagentResult]] = {
            slash: list(responses) for slash, responses in scripted.items()
        }
        self.calls: list[tuple[str, str, float]] = []

    def invoke(self, slash: str, args_text: str, budget_usd: float) -> SubagentResult:
        self.calls.append((slash, args_text, budget_usd))
        queue = self._scripted.get(slash, [])
        if not queue:
            raise RuntimeError(f"DummySubagent: no scripted response for {slash}")
        return queue.pop(0)


def make_result(
    raw_stdout: str,
    *,
    exit_code: int = 0,
    cost_usd: float = 0.05,
    session_id: str = "00000000-0000-0000-0000-000000000000",
    raw_stderr: str = "",
) -> SubagentResult:
    """Convenience constructor for tests / fixtures."""
    return SubagentResult(
        exit_code=exit_code,
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
        cost_usd=cost_usd,
        session_id=session_id,
    )


_RUN_DEV_LOOP_ADDENDUM = (
    "\n"
    "重要 (Manager からの追加指示):\n"
    "- verdict が `safe to merge` または `confirm before merge` の場合、"
    "実装した変更を **Bash 経由で `git add -A` + `git commit`** してから "
    "/pr-creation を呼ぶこと。Edit/Write tool でファイルを書いただけでは "
    "未 commit のままで Manager が PR を見つけられない。\n"
    "  (注: ローカル Git 操作 (`git add` / `git commit` / `git push`) に "
    "MCP 相当のツールは存在しないため Bash 一択)\n"
    "- /pr-creation 内で PR を作成すること。**推奨は MCP github の "
    "`mcp__github__create_pull_request`**。MCP server が利用できない場合は "
    "Bash の `gh pr create` でフォールバックして可。いずれの経路でも "
    "Output Format の `# PR Summary` セクションを **PR を実際に作成済みの "
    "証跡** として記述すること。\n"
    "- verdict が `fix before merge` の場合のみ commit / PR 作成を行わない。\n"
)


def build_invocation_prompt(slash: str, args_text: str) -> str:
    """The exact prompt format used to invoke any of the existing slash commands.

    Matches the template in `.claude/skills/orchestrator.md` so the subagent
    behaves identically whether invoked by `/orchestrate` (LLM router) or by
    Manager (state machine).

    For `/run-dev-loop` we append a Manager-specific addendum that makes the
    implicit "commit + create PR" step explicit. The /run-dev-loop slash spec
    says step 6/7 prepares "PR-ready output" and calls /pr-creation, but it
    does not literally spell out the `git commit` call — subagents sometimes
    skip the git/gh tool use and leave changes untracked, which makes the
    VERIFY_PR stage fail because no PR exists. The addendum closes that gap
    without modifying the slash command file (which is owned externally).
    """
    name = slash.lstrip("/")
    base = (
        f"あなたは /{name} として動作する。\n"
        f"以下の command ファイルを最初に Read tool で読み、"
        f"その Required Reading セクションに書かれた全ファイルを読んでから開始すること。\n"
        f"- .claude/commands/{name}.md\n"
        f"\n"
        f"入力 ($ARGUMENTS):\n"
        f"{args_text}\n"
        f"\n"
        f"出力は .claude/commands/{name}.md の Output Format に厳密に従うこと。\n"
    )
    if name == "run-dev-loop":
        base += _RUN_DEV_LOOP_ADDENDUM
    return base


@dataclass
class RealSubagent:
    """Phase 3+ implementation: shells out to `claude -p`.

    Defaults are tuned to keep cost on the Claude Code OAuth (Max plan) path:

    - `env=sanitized_env()`: strip `ANTHROPIC_*` from the spawned env so a
      stray `.env` line or parent injection can't silently switch billing to
      API credit. This is the primary defense — Max plan stays in effect
      because keychain OAuth is the only remaining auth path.
    - `bare=False` (default): in CLI v2.1+ `--bare` *disables* keychain/OAuth
      reads (only API key / apiKeyHelper auth survives). Combined with
      `sanitized_env()` stripping `ANTHROPIC_*`, `--bare` leaves no usable
      auth path → spawned `claude -p` exits with "Not logged in". We keep
      the flag as a knob (for setups that intentionally pass an API key via
      `--settings`), but default it off so keychain works.
    - `--dangerously-skip-permissions`: required because non-interactive `-p`
      mode can't surface a tool-permission prompt. Manager's own kill-switch /
      cost / diff limit / NEEDS_HUMAN escalation is the safety net.
    - `--output-format=json`: gives us `result` (text), `total_cost_usd`, and
      `session_id` for telemetry.
    - `--no-session-persistence`: failed runs leave nothing on disk.
    """

    repo_root: Path
    claude_bin: str = "claude"
    timeout: int = SUBAGENT_TIMEOUT_SECONDS
    extra_add_dirs: tuple[Path, ...] = ()
    dangerously_skip_permissions: bool = True
    bare: bool = False
    # Opt-in: map slash command name (without leading `/`) to a JSON Schema
    # file. When set, `--json-schema <contents>` is appended to argv, forcing
    # the CLI to validate the model's output against the schema (Anthropic
    # Structured Outputs, GA on Claude 4.x). The slash command's Markdown
    # Output Format becomes secondary — the CLI overrides it. Default empty
    # keeps the legacy Markdown contract for every stage. See
    # `manager/schemas/triage.json` for the first migrated schema.
    json_schemas: Mapping[str, Path] = field(default_factory=dict)

    def invoke(self, slash: str, args_text: str, budget_usd: float) -> SubagentResult:
        session_id = str(uuid.uuid4())
        prompt = build_invocation_prompt(slash, args_text)
        argv = self._build_argv(session_id, budget_usd, slash)
        result = self._run_with_transient_backoff(argv, prompt)
        if isinstance(result, CommandTimeout):
            return SubagentResult(
                exit_code=124,
                raw_stdout="",
                raw_stderr=str(result),
                cost_usd=0.0,
                session_id=session_id,
            )
        if result.exit_code != 0:
            # A failed subagent (exit != 0) can still have spent real tokens —
            # e.g. `claude -p` exits non-zero with `subtype=error_max_budget_usd`
            # after burning the entire per-stage budget. Parse cost out of the
            # JSON envelope even on failure so the epic-level accounting is
            # honest; `_decode_claude_json` returns 0.0 if the body isn't a
            # valid claude-p result envelope, which is the right fallback.
            _, failed_cost, _ = _decode_claude_json(result.stdout)
            return SubagentResult(
                exit_code=result.exit_code,
                raw_stdout=result.stdout,
                raw_stderr=result.stderr,
                cost_usd=failed_cost,
                session_id=session_id,
            )
        text, cost, returned_session = _decode_claude_json(result.stdout)
        return SubagentResult(
            exit_code=0,
            raw_stdout=text,
            raw_stderr=result.stderr,
            cost_usd=cost,
            session_id=returned_session or session_id,
        )

    def _run_with_transient_backoff(self, argv: list[str], prompt: str):  # type: ignore[no-untyped-def]
        """Retry on transient stderr patterns (429 / 5xx / connection reset).

        Permanent failures (auth, bad args, schema mismatch) come back fast
        without matching `_TRANSIENT_STDERR_RE` and are returned as-is.
        """
        env = sanitized_env()
        last = None
        attempts = len(NETWORK_BACKOFF_SECONDS)
        for attempt, delay in enumerate(NETWORK_BACKOFF_SECONDS):
            try:
                result = run(argv, stdin=prompt, timeout=self.timeout, env=env)
            except CommandTimeout as exc:
                return exc
            if not is_transient_failure(result.exit_code, result.stderr):
                return result
            last = result
            if attempt < attempts - 1:
                time.sleep(delay)
        assert last is not None
        return last

    def _build_argv(
        self, session_id: str, budget_usd: float, slash: str
    ) -> list[str]:
        argv: list[str] = [
            self.claude_bin,
            "-p",
            "--output-format", "json",
            "--input-format", "text",
            "--no-session-persistence",
            "--max-budget-usd", f"{budget_usd}",
            "--session-id", session_id,
            "--add-dir", str(self.repo_root),
        ]
        if self.bare:
            argv.append("--bare")
        if self.dangerously_skip_permissions:
            argv.append("--dangerously-skip-permissions")
        for extra in self.extra_add_dirs:
            argv.extend(["--add-dir", str(extra)])
        schema_path = self.json_schemas.get(slash.lstrip("/"))
        if schema_path is not None:
            argv.extend(["--json-schema", schema_path.read_text(encoding="utf-8")])
        return argv


def _decode_claude_json(stdout: str) -> tuple[str, float, str | None]:
    """Extract `result`, `total_cost_usd`, `session_id` from `claude -p --output-format json`.

    Defensive: if the wrapper schema changes, fall back to treating stdout as raw text.
    """
    stripped = stdout.strip()
    if not stripped:
        return "", 0.0, None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stdout, 0.0, None
    if not isinstance(payload, dict):
        return stdout, 0.0, None
    text_value = payload.get("result")
    text = text_value if isinstance(text_value, str) else stdout
    cost_raw = payload.get("total_cost_usd", 0.0)
    cost = float(cost_raw) if isinstance(cost_raw, (int, float)) else 0.0
    session_raw = payload.get("session_id")
    session = session_raw if isinstance(session_raw, str) else None
    return text, cost, session
