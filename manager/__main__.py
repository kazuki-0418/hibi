"""Entry point for the Manager Agent.

Default mode is `--dry-run` (Dummy* implementations) for safety. Pass `--live`
to shell out to real `claude -p` and `gh` commands.

Subcommands:

    python -m manager run <epic#>     start (or resume) an epic
    python -m manager resume <epic#>  alias for `run` (loads existing state)
    python -m manager status <epic#>  print epic + per-child summary, no exec

The `--retry` flag (with `run`/`resume`) puts the named failed children back at
the head of the queue and resets their state to INIT before re-attempting.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .escalate import DummyEscalator, Escalator, RealEscalator
from .git_ops import DummyGitOps, GitOps, RealGitOps
from .limits import EXIT_LOCK_TAKEN
from .runner import Runner
from .state_store import LockTaken, StateStore
from .subagent import DummySubagent, RealSubagent, Subagent

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = REPO_ROOT / ".claude" / "state"


def _build_dummy(epic_issue: int, children: list[int]) -> tuple[Subagent, GitOps, Escalator]:
    return (
        DummySubagent(scripted={}),
        DummyGitOps(child_listing={epic_issue: children}),
        DummyEscalator(),
    )


def _build_live() -> tuple[Subagent, GitOps, Escalator]:
    return (
        RealSubagent(repo_root=REPO_ROOT),
        RealGitOps(repo_root=REPO_ROOT),
        RealEscalator(repo_root=REPO_ROOT),
    )


def _cmd_run(args: argparse.Namespace) -> int:
    if args.live:
        subagent, git_ops, escalator = _build_live()
    else:
        subagent, git_ops, escalator = _build_dummy(args.epic_issue, args.children)
    runner = Runner(
        state_store=StateStore(STATE_ROOT),
        subagent=subagent,
        git_ops=git_ops,
        escalator=escalator,
        repo_root=REPO_ROOT,
    )
    try:
        return runner.run_epic(
            args.epic_issue,
            slug=args.slug,
            retry_failed=args.retry or [],
        )
    except LockTaken as exc:
        print(f"manager: {exc}", file=sys.stderr)
        return EXIT_LOCK_TAKEN


def _cmd_status(args: argparse.Namespace) -> int:
    store = StateStore(STATE_ROOT)
    epic_path = store.epic_path(args.epic_issue)
    if not epic_path.exists():
        print(f"no state for epic #{args.epic_issue}", file=sys.stderr)
        return 1
    epic = json.loads(epic_path.read_text(encoding="utf-8"))
    print(json.dumps(epic, indent=2, sort_keys=True))
    children_dir = store.epic_dir(args.epic_issue) / "children"
    if children_dir.exists():
        for sub in sorted(children_dir.iterdir()):
            state_file = sub / "state.json"
            if state_file.exists():
                child = json.loads(state_file.read_text(encoding="utf-8"))
                print(
                    f"  child #{child['issue_number']}: {child['status']} "
                    f"(cost ${child.get('cost_usd', 0):.4f})"
                )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("run", "resume"):
        p = sub.add_parser(name, help="start or resume an epic")
        p.add_argument("epic_issue", type=int)
        p.add_argument("--slug", default="epic", help="branch slug suffix")
        p.add_argument("--live", action="store_true", help="use claude -p / gh / git")
        p.add_argument("--children", type=int, nargs="*", default=[],
                       help="dry-run only: explicit child issue numbers")
        p.add_argument("--retry", type=int, nargs="*", default=[],
                       help="failed child issue numbers to reset and re-attempt")
        p.set_defaults(func=_cmd_run)

    p = sub.add_parser("status", help="print epic + per-child summary")
    p.add_argument("epic_issue", type=int)
    p.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
