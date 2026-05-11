"""Subprocess helpers shared by Real* implementations.

Centralized so timeout / retry / error wrapping rules apply uniformly to every
external command Manager runs.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Sequence

from .limits import NETWORK_BACKOFF_SECONDS, SUBAGENT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class CommandTimeout(Exception):
    pass


def run(
    argv: Sequence[str],
    *,
    stdin: str | None = None,
    timeout: int = SUBAGENT_TIMEOUT_SECONDS,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a command synchronously. Never raises on non-zero exit; raises on timeout.

    `env=None` inherits the parent env. Pass an explicit dict to scrub specific
    variables (used by RealSubagent to keep ANTHROPIC_* out of `claude -p`).
    """
    started = time.monotonic()
    try:
        proc = subprocess.run(
            list(argv),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeout(f"timeout after {timeout}s: {' '.join(argv[:3])}...") from exc
    return CommandResult(
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        elapsed_seconds=time.monotonic() - started,
    )


def run_with_backoff(
    argv: Sequence[str],
    *,
    stdin: str | None = None,
    timeout: int = SUBAGENT_TIMEOUT_SECONDS,
    cwd: str | None = None,
    retry_on_exit_codes: frozenset[int] = frozenset(),
) -> CommandResult:
    """Run with exponential backoff for transient failures.

    Retries when exit_code is in `retry_on_exit_codes`. If still failing after
    NETWORK_BACKOFF_SECONDS attempts, returns the last result (caller decides).
    """
    last: CommandResult | None = None
    for attempt, delay in enumerate(NETWORK_BACKOFF_SECONDS):
        result = run(argv, stdin=stdin, timeout=timeout, cwd=cwd)
        if result.exit_code == 0 or result.exit_code not in retry_on_exit_codes:
            return result
        last = result
        if attempt < len(NETWORK_BACKOFF_SECONDS) - 1:
            time.sleep(delay)
    assert last is not None
    return last
