"""Tests for goal-conditioned summarize parsing (KAZ-202)."""

from summarize_goal import parse_summarize_response


def test_parse_summarize_response_splits_blocks() -> None:
    raw = """---要約---
・一行目の事実。
・二行目の事実。
・三行目の事実。
---関連---
・プロジェクト焦点への関連注記。"""
    parsed = parse_summarize_response(raw)
    assert "一行目" in parsed.summary
    assert "関連注記" in parsed.goal_note
    assert "---要約---" not in parsed.summary


def test_parse_legacy_three_line_format() -> None:
    raw = "・のみの従来形式。\n・二行目。\n・三行目。"
    parsed = parse_summarize_response(raw)
    assert parsed.summary == raw
    assert parsed.goal_note == ""
