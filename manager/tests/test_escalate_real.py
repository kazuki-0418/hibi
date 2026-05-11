from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from manager import escalate as esc_mod
from manager._subprocess import CommandResult
from manager.escalate import RealEscalator
from manager.git_ops import GitOpsError


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exit_code: int = 0,
    stderr: str = "",
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_run(
        argv: Sequence[str],
        *,
        stdin: str | None = None,
        timeout: int = 0,
        cwd: str | None = None,
    ) -> CommandResult:
        captured["argv"] = list(argv)
        captured["stdin"] = stdin
        captured["cwd"] = cwd
        return CommandResult(exit_code=exit_code, stdout="", stderr=stderr, elapsed_seconds=0.0)

    monkeypatch.setattr(esc_mod, "run", fake_run)
    return captured


def test_real_escalator_posts_via_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _patch(monkeypatch)
    esc = RealEscalator(repo_root=tmp_path)
    body = "## Detail\nMulti-line\nbody with `code` and # markers"
    esc.comment(42, body)
    assert captured["argv"] == ["gh", "issue", "comment", "42", "-F", "-"]
    assert captured["stdin"] == body
    assert captured["cwd"] == str(tmp_path)


def test_real_escalator_raises_on_gh_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, exit_code=1, stderr="auth required")
    esc = RealEscalator(repo_root=tmp_path)
    with pytest.raises(GitOpsError) as exc:
        esc.comment(42, "hi")
    assert "auth required" in str(exc.value)
