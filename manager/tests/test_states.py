from __future__ import annotations

import pytest

from manager.states import LEGAL_TRANSITIONS, TERMINAL_STATES, is_legal


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in TERMINAL_STATES:
        assert not [t for t in LEGAL_TRANSITIONS if t.src == state], (
            f"terminal state {state} must not have outgoing transitions"
        )


def test_every_non_terminal_state_can_reach_a_terminal() -> None:
    # BFS from every src to confirm no orphan loop exists.
    graph: dict[str, set[str]] = {}
    for t in LEGAL_TRANSITIONS:
        graph.setdefault(t.src, set()).add(t.dst)
    for src in graph:
        seen: set[str] = set()
        stack = [src]
        reached_terminal = False
        while stack:
            node = stack.pop()
            if node in TERMINAL_STATES:
                reached_terminal = True
                break
            if node in seen:
                continue
            seen.add(node)
            stack.extend(graph.get(node, ()))
        assert reached_terminal, f"{src} cannot reach a terminal state"


def test_is_legal_accepts_known_transition() -> None:
    assert is_legal("TRIAGE", "PACKETIZE")


def test_is_legal_rejects_unknown_transition() -> None:
    assert not is_legal("TRIAGE", "DONE")
    assert not is_legal("DONE", "INIT")
