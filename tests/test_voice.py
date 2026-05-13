"""Voice & tone guard tests.

`voice.check_voice_violations` は design-system/README.md "What we don't do"
を観測する pure function。配信を止めない検出器なので、ここで検証するのは:

- 禁止ワード (substring 一致) が拾われる
- 感嘆符 (半角/全角) が拾われる
- 絵文字が拾われる
- 規範的な要約 (Hibi voice 準拠) は violations=[] になる

また `daily_news.summarize` 経由でも、API 呼び出しを monkeypatch でモックして
違反検出時に warning ログが出ることを 1 ケース確認する。Claude / Neon /
OpenAI / Gmail は呼ばない。
"""
from __future__ import annotations

import logging
from typing import Callable

import pytest

import daily_news
from voice import check_voice_violations


# ============================================================
# check_voice_violations: pure function tests
# ============================================================
def test_check_voice_violations_detects_clickbait_word() -> None:
    """「驚愕の発表」のような典型的なクリックベイト動詞を拾う。"""
    violations = check_voice_violations("驚愕の発表があった。")
    assert "驚愕" in violations


def test_check_voice_violations_detects_marketing_cta_and_exclamation() -> None:
    """二人称呼びかけ + マーケ CTA + 感嘆符の複合ケース。"""
    violations = check_voice_violations("読者の皆様、必見!")
    assert "読者の皆様" in violations
    assert "必見" in violations
    assert "感嘆符" in violations


def test_check_voice_violations_detects_fullwidth_exclamation() -> None:
    """全角感嘆符「！」も検出する (design-system は両方禁止)。"""
    violations = check_voice_violations("発表があった！")
    assert "感嘆符" in violations


def test_check_voice_violations_detects_emoji() -> None:
    """絵文字 (📅 など Misc Symbols and Pictographs) を検出する。"""
    violations = check_voice_violations("📅 イベントが開催される。")
    assert "絵文字" in violations


def test_check_voice_violations_clean_summary_returns_empty() -> None:
    """design-system 準拠の要約は違反なし。

    README.md の "Example summary block" を踏襲した文面。三人称・宣言的・
    句点で終わる・記号は中黒のみ。
    """
    clean = "・Anthropic が Claude 4.6 を発表した。"
    assert check_voice_violations(clean) == []


def test_check_voice_violations_allows_middot_separator() -> None:
    """「・」(middot, U+30FB) は design-system が明示的に許可する唯一の記号。

    絵文字検出レンジに含まれないことを境界条件として確認する。
    """
    assert check_voice_violations("・前提・背景・結論") == []


def test_check_voice_violations_detects_first_person() -> None:
    """一人称「私」「僕」は newspaper voice では使わない。"""
    assert "私" in check_voice_violations("私はこう考える。")
    assert "僕" in check_voice_violations("僕の意見は違う。")


# ============================================================
# summarize: integration with logging (Claude API is mocked)
# ============================================================
class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContentBlock(text)]


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text
        # behavior 検証のため呼び出し時の引数も拾える形にしておく
        self.last_kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> _FakeResponse:
        self.last_kwargs = kwargs
        return _FakeResponse(self._text)


class _FakeAnthropic:
    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


def _fake_client(text: str) -> _FakeAnthropic:
    return _FakeAnthropic(text)


def test_summarize_logs_warning_on_voice_violation(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude の戻り値に違反ワードがあると warning ログが出る。配信は通す。

    monkeypatch で `Anthropic` クライアントを差し替え、外部 API を一切
    呼ばずに `summarize()` の post-processing パスだけを検証する。
    """
    dirty_summary = "・驚愕の発表があった!"
    fake = _fake_client(dirty_summary)

    with caplog.at_level(logging.WARNING, logger=daily_news.log.name):
        result = daily_news.summarize(fake, title="t", content="c" * 600)

    # 配信は通す (= 戻り値はそのまま返される)
    assert result == dirty_summary

    # warning が出ている & 検出語が含まれている
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records, "expected a WARNING log for voice violations"
    msg = warning_records[0].getMessage()
    assert "voice violations" in msg
    assert "驚愕" in msg
    assert "感嘆符" in msg


def test_summarize_no_warning_for_clean_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """規範的な出力に対しては warning が出ない (false-positive 防止)。"""
    clean = "・Anthropic が Claude 4.6 を発表した。\n・API は既存キーで利用できる。\n・料金は前世代と同じ。"
    fake = _fake_client(clean)

    with caplog.at_level(logging.WARNING, logger=daily_news.log.name):
        result = daily_news.summarize(fake, title="t", content="c" * 600)

    assert result == clean
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_summarize_skips_check_on_empty_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Claude が defended (空文字列) を返した場合、violation チェックは
    skip され warning は出ない。

    空文字列に対する false-positive (例: 絵文字検出ロジックの誤動作で空が
    引っかかる) を未然に防ぐ境界条件テスト。
    """
    fake = _fake_client("")

    with caplog.at_level(logging.WARNING, logger=daily_news.log.name):
        result = daily_news.summarize(fake, title="t", content="c" * 600)

    assert result == ""
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
