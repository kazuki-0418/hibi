"""Tests for English output practice (KAZ-203)."""

import json

import english_practice as ep


def test_pick_english_anchor_prefers_goal_slot() -> None:
    delivered = [
        {"digest_slot": "challenge", "title": "c"},
        {"digest_slot": "goal", "title": "g"},
    ]
    anchor = ep.pick_english_anchor(delivered)
    assert anchor is not None
    assert anchor["title"] == "g"


def test_build_paste_request_includes_naturalness_instruction() -> None:
    paste = ep.build_paste_request(
        "In English: react to the story. （まず声に出してから書く。）",
        article_title="Test Article",
        article_summary="要約本文。",
        goal_snippet="Project: hibi",
    )
    assert "natural English" in paste
    assert "not grammar nitpicking" in paste
    assert "spoke my thoughts aloud" in paste
    assert "Test Article" in paste


def test_generate_english_practice_uses_claude_json(monkeypatch) -> None:
    class FakeBlock:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.content = [FakeBlock(text)]

    class FakeMessages:
        def create(self, **_kwargs):
            payload = json.dumps(
                {
                    "prompt_line": (
                        "In English (2–3 sentences): tie this to Monogatari. "
                        "（まず声に出してから書く。）"
                    )
                }
            )
            return FakeResponse(payload)

    class FakeClient:
        messages = FakeMessages()

    anchor = {"title": "React 19 ships", "summary": "・要点。"}
    result = ep.generate_english_practice(
        FakeClient(),
        anchor,
        goal_focus_text="Goal: ship Monogatari",
        project_slugs=("monogatari",),
    )
    assert "Monogatari" in result.prompt_line
    assert "Paste into Claude" not in result.paste_request
    assert "natural English" in result.paste_request
