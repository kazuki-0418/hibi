"""Tests for `idea_mining.prompts._profile_block`.

Helper が loader の戻り値をそのまま返す薄い pass-through であることを検証
する (将来 wrap を入れたら本テストを更新する)。
"""
from __future__ import annotations

import pytest

from idea_mining.prompts import _profile_block


def test_helper_returns_loader_output(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "## stub profile block\n\n- 必須項目: テスト固定\n"
    monkeypatch.setattr(_profile_block, "_load_profile", lambda: sentinel)

    assert _profile_block.profile_block() == sentinel
