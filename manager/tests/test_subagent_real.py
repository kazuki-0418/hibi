from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pytest

from manager import _subprocess as sp_mod
from manager import subagent as sub_mod
from manager._subprocess import CommandResult, CommandTimeout
from manager.subagent import RealSubagent, build_invocation_prompt


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_run(
        argv: Sequence[str],
        *,
        stdin: str | None = None,
        timeout: int = 0,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        captured["argv"] = list(argv)
        captured["stdin"] = stdin
        captured["timeout"] = timeout
        captured["cwd"] = cwd
        captured["env"] = env
        payload = json.dumps(
            {
                "result": "# Execution Readiness\n- ready\n",
                "total_cost_usd": 0.0123,
                "session_id": "session-from-claude",
                "is_error": False,
            }
        )
        return CommandResult(exit_code=0, stdout=payload, stderr="", elapsed_seconds=0.1)

    monkeypatch.setattr(sub_mod, "run", fake_run)
    return captured


def test_real_subagent_constructs_expected_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _capture(monkeypatch)
    sub = RealSubagent(repo_root=tmp_path, claude_bin="claude")
    sub.invoke("/triage-issue", "issue body here", budget_usd=1.0)

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert "--no-session-persistence" in argv
    assert "--max-budget-usd" in argv and argv[argv.index("--max-budget-usd") + 1] == "1.0"
    assert "--bare" not in argv, (
        "default must NOT pass --bare: in CLI v2.1+ --bare disables keychain/OAuth "
        "and sanitized_env() strips ANTHROPIC_*, leaving no auth path"
    )
    assert "--dangerously-skip-permissions" in argv
    assert "--add-dir" in argv and str(tmp_path) in argv
    # session-id is a uuid we generated
    sid_idx = argv.index("--session-id")
    assert isinstance(argv[sid_idx + 1], str) and len(argv[sid_idx + 1]) == 36


def test_real_subagent_passes_prompt_via_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _capture(monkeypatch)
    sub = RealSubagent(repo_root=tmp_path)
    sub.invoke("/triage-issue", "MY ISSUE BODY", budget_usd=0.5)
    stdin = captured["stdin"]
    assert isinstance(stdin, str)
    assert "/triage-issue" in stdin
    assert ".claude/commands/triage-issue.md" in stdin
    assert "MY ISSUE BODY" in stdin


def test_real_subagent_extracts_text_cost_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _capture(monkeypatch)
    sub = RealSubagent(repo_root=tmp_path)
    result = sub.invoke("/triage-issue", "x", budget_usd=1.0)
    assert result.exit_code == 0
    assert result.raw_stdout.strip().startswith("# Execution Readiness")
    assert result.cost_usd == pytest.approx(0.0123)
    assert result.session_id == "session-from-claude"


def test_real_subagent_handles_non_json_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(argv: Sequence[str], **kwargs: object) -> CommandResult:
        return CommandResult(exit_code=0, stdout="raw plain text", stderr="", elapsed_seconds=0.0)

    monkeypatch.setattr(sub_mod, "run", fake_run)
    sub = RealSubagent(repo_root=tmp_path)
    result = sub.invoke("/triage-issue", "x", budget_usd=1.0)
    assert result.exit_code == 0
    assert result.raw_stdout == "raw plain text"
    assert result.cost_usd == 0.0


def test_real_subagent_handles_non_zero_exit_non_transient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Permanent failure: returned as-is, no retry."""
    calls = {"n": 0}

    def fake_run(argv: Sequence[str], **kwargs: object) -> CommandResult:
        calls["n"] += 1
        return CommandResult(exit_code=1, stdout="", stderr="bad arguments", elapsed_seconds=0.0)

    monkeypatch.setattr(sub_mod, "run", fake_run)
    sub = RealSubagent(repo_root=tmp_path)
    result = sub.invoke("/triage-issue", "x", budget_usd=1.0)
    assert result.exit_code == 1
    assert "bad arguments" in result.raw_stderr
    assert calls["n"] == 1, "non-transient failure should NOT retry"


def test_real_subagent_extracts_cost_on_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed claude-p can still report cost via the JSON envelope (e.g.
    `error_max_budget_usd` burns the full budget then exits non-zero). The
    SubagentResult.cost_usd must reflect that real spend so epic-level
    accounting is honest.
    """
    failed_payload = json.dumps({
        "type": "result",
        "subtype": "error_max_budget_usd",
        "is_error": True,
        "result": "Reached maximum budget ($10)",
        "total_cost_usd": 10.057,
        "session_id": "burned-budget-session",
    })

    def fake_run(argv: Sequence[str], **kwargs: object) -> CommandResult:
        return CommandResult(
            exit_code=1, stdout=failed_payload, stderr="", elapsed_seconds=0.0
        )

    monkeypatch.setattr(sub_mod, "run", fake_run)
    sub = RealSubagent(repo_root=tmp_path)
    result = sub.invoke("/run-dev-loop", "x", budget_usd=10.0)
    assert result.exit_code == 1, "failure surfaces as non-zero"
    assert result.cost_usd == pytest.approx(10.057), (
        "cost from JSON envelope must reach the caller even when claude-p failed; "
        "otherwise epic accounting silently under-counts every budget-exhausted retry"
    )


def test_real_subagent_retries_on_transient_then_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Transient stderr triggers backoff retry. We mock time.sleep to keep fast."""
    calls = {"n": 0}

    def fake_run(argv: Sequence[str], **kwargs: object) -> CommandResult:
        calls["n"] += 1
        return CommandResult(exit_code=1, stdout="", stderr="429 rate-limit hit", elapsed_seconds=0.0)

    monkeypatch.setattr(sub_mod, "run", fake_run)
    monkeypatch.setattr(sub_mod.time, "sleep", lambda _s: None)
    sub = RealSubagent(repo_root=tmp_path)
    result = sub.invoke("/triage-issue", "x", budget_usd=1.0)
    assert result.exit_code == 1
    assert calls["n"] == 3, "should retry up to NETWORK_BACKOFF_SECONDS attempts"


def test_real_subagent_succeeds_after_one_transient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First attempt 429, second attempt success."""
    calls = {"n": 0}
    success_payload = '{"result": "# Execution Readiness\\n- ready\\n", "total_cost_usd": 0.01}'

    def fake_run(argv: Sequence[str], **kwargs: object) -> CommandResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return CommandResult(1, "", "503 Service unavailable", 0.0)
        return CommandResult(0, success_payload, "", 0.0)

    monkeypatch.setattr(sub_mod, "run", fake_run)
    monkeypatch.setattr(sub_mod.time, "sleep", lambda _s: None)
    sub = RealSubagent(repo_root=tmp_path)
    result = sub.invoke("/triage-issue", "x", budget_usd=1.0)
    assert result.exit_code == 0
    assert calls["n"] == 2
    assert "ready" in result.raw_stdout


def test_is_transient_failure_classifier() -> None:
    from manager.subagent import is_transient_failure
    assert is_transient_failure(1, "Anthropic API overloaded, retry") is True
    assert is_transient_failure(1, "429 Too Many Requests") is True
    assert is_transient_failure(1, "ECONNRESET") is True
    assert is_transient_failure(1, "Invalid argument: --bogus-flag") is False
    assert is_transient_failure(0, "anything") is False  # success is not transient


def test_real_subagent_strips_anthropic_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ANTHROPIC_* env vars must NOT reach the spawned `claude -p`."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak-this-must-not-pass")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://leak.example")
    monkeypatch.setenv("PATH", "/usr/bin")
    captured = _capture(monkeypatch)
    sub = RealSubagent(repo_root=tmp_path)
    sub.invoke("/triage-issue", "x", budget_usd=1.0)
    env = captured["env"]
    assert isinstance(env, dict)
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert env.get("PATH") == "/usr/bin", "non-ANTHROPIC env must pass through"


def test_sanitized_env_drops_only_anthropic_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manager.subagent import sanitized_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_LOG", "info")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = sanitized_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_LOG" not in env
    assert env.get("CLAUDE_CODE_SESSION_ID") == "abc", "claude code own env stays"
    assert env.get("PATH") == "/usr/bin"


def test_real_subagent_handles_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(argv: Sequence[str], **kwargs: object) -> CommandResult:
        raise CommandTimeout("timeout after 900s: claude -p ...")

    monkeypatch.setattr(sub_mod, "run", fake_run)
    sub = RealSubagent(repo_root=tmp_path)
    result = sub.invoke("/triage-issue", "x", budget_usd=1.0)
    assert result.exit_code == 124
    assert "timeout" in result.raw_stderr


def test_build_invocation_prompt_includes_required_reading_directive() -> None:
    prompt = build_invocation_prompt("/spec-architect", "PACKET YAML HERE")
    assert "/spec-architect" in prompt
    assert ".claude/commands/spec-architect.md" in prompt
    assert "Required Reading" in prompt
    assert "PACKET YAML HERE" in prompt
    assert "Output Format" in prompt
