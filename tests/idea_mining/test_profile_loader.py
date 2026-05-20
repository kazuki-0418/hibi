"""Tests for `idea_mining.profile_loader`.

Vault profile loader が:
- 2 ファイルの Markdown 全文を結合して返すこと
- env 未設定 / ファイル欠落で `RuntimeError` を投げること (fails-closed)
- `HIBI_VAULT_OPTIONAL=1` のときだけ空文字列を返すこと
を検証する。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from idea_mining import profile_loader
from idea_mining.profile_loader import (
    OPTIONAL_ENV,
    PROFILE_SUBPATH,
    VAULT_ROOT_ENV,
    load,
)

USER_CONSTRAINTS_FIXTURE = """\
# User Constraints

## 必須条件
- 必須項目: 個人プロジェクト前提で運用できること
- 学習信号はクリックのみ

## 避けるパターン
- ありきたりな汎用 AI ニュースリーダー
"""

NEGATIVE_EXAMPLES_FIXTURE = """\
# Negative Examples

## Aesthetic OS
- 理由: コンセプトが先行し、実運用での学習信号が貧弱
"""


def _write_profile(tmp_path: Path) -> Path:
    profile_dir = tmp_path / PROFILE_SUBPATH
    profile_dir.mkdir(parents=True)
    (profile_dir / "user-constraints.md").write_text(
        USER_CONSTRAINTS_FIXTURE, encoding="utf-8"
    )
    (profile_dir / "negative-examples.md").write_text(
        NEGATIVE_EXAMPLES_FIXTURE, encoding="utf-8"
    )
    return tmp_path


def test_load_concatenates_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _write_profile(tmp_path)
    monkeypatch.setenv(VAULT_ROOT_ENV, str(vault_root))
    monkeypatch.delenv(OPTIONAL_ENV, raising=False)

    result = load()

    assert USER_CONSTRAINTS_FIXTURE in result
    assert NEGATIVE_EXAMPLES_FIXTURE in result
    assert result.index(USER_CONSTRAINTS_FIXTURE) < result.index(
        NEGATIVE_EXAMPLES_FIXTURE
    )


def test_load_includes_required_user_constraint_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _write_profile(tmp_path)
    monkeypatch.setenv(VAULT_ROOT_ENV, str(vault_root))
    monkeypatch.delenv(OPTIONAL_ENV, raising=False)

    result = load()

    assert "必須項目: 個人プロジェクト前提で運用できること" in result


def test_load_raises_when_vault_root_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(VAULT_ROOT_ENV, raising=False)
    monkeypatch.delenv(OPTIONAL_ENV, raising=False)

    with pytest.raises(RuntimeError, match=VAULT_ROOT_ENV):
        load()


def test_load_raises_when_profile_files_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / PROFILE_SUBPATH).mkdir(parents=True)
    monkeypatch.setenv(VAULT_ROOT_ENV, str(tmp_path))
    monkeypatch.delenv(OPTIONAL_ENV, raising=False)

    with pytest.raises(RuntimeError, match="Profile file missing"):
        load()


def test_load_returns_empty_when_hibi_vault_optional_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(VAULT_ROOT_ENV, raising=False)
    monkeypatch.setenv(OPTIONAL_ENV, "1")

    assert load() == ""


def test_load_returns_empty_when_optional_and_files_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAULT_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(OPTIONAL_ENV, "1")

    assert load() == ""


def test_profile_subpath_is_fixed() -> None:
    assert PROFILE_SUBPATH == "10_projects/hibi/idea-mining/profile"
    assert profile_loader.PROFILE_FILES == (
        "user-constraints.md",
        "negative-examples.md",
    )
