"""Tests for `daily_news.generate_edition_meta` (Issue #53).

Covered behaviors:
- 正常系: Claude が valid JSON を返したとき、parsed standfirst / daily_title
  をそのまま返す。
- 異常系1: Claude が JSON でない文字列を返したとき、フォールバック値
  (``今朝のN本。`` / titles joined by ``" / "``) が返る。
- 異常系2: Claude API 呼び出しが例外を投げたとき、フォールバック値が返る。
- 異常系3: JSON は parse できるがフィールドが欠けているとき、フォールバック。
- 境界: articles が空のとき。
- 後処理ガード: 禁止ワードを含む生成結果は log.warning だけ出て、値は通す。

外部 API (Claude) はモック。実呼び出しテストは増やさない (test-agent.md)。
"""
from __future__ import annotations

import logging
from typing import Callable
from unittest.mock import MagicMock

import pytest

import daily_news


SAMPLE_ARTICLES: list[dict] = [
    {
        "title": "Anthropic、Claude Sonnet 4.6 を公開",
        "summary": "・長文要約とコード生成の精度が向上した。\n"
                   "・既存 API キーで即時利用可能。\n"
                   "・開発者向けにバッチ API もベータ提供開始。",
    },
    {
        "title": "CSS Anchor Positioning がブラウザ三社で揃う",
        "summary": "・Firefox 138 で実装が揃った。\n"
                   "・Chrome / Safari は既に対応済み。\n"
                   "・ポップオーバー UI のロジックが簡潔になる。",
    },
    {
        "title": "東京の AI スタートアップ二社が同日に調達発表",
        "summary": "・Sakana AI 系列のスピンアウトが Series A で十二億円調達。\n"
                   "・もう一社は seed で三億円。\n"
                   "・両社とも在日エンジニア採用を強化する。",
    },
]


def _make_fake_anthropic(text_response: str) -> MagicMock:
    """``client.messages.create`` を text_response を返すように差し替えた
    MagicMock を返す。Anthropic SDK の response 構造 (``content[0].text``)
    を最小限に模倣する。"""
    fake = MagicMock()
    fake_message = MagicMock()
    fake_content = MagicMock()
    fake_content.text = text_response
    fake_message.content = [fake_content]
    fake.messages.create.return_value = fake_message
    return fake


def _make_failing_anthropic(exc: BaseException) -> MagicMock:
    """``client.messages.create`` が例外を投げるように差し替えた MagicMock。"""
    fake = MagicMock()
    fake.messages.create.side_effect = exc
    return fake


# ── 正常系: Claude が valid JSON を返す ────────────────────────────────


def test_generate_edition_meta_parses_valid_json() -> None:
    fake_client = _make_fake_anthropic(
        '{"standfirst": "今朝の3本。静かな朝の観察。", '
        '"daily_title": "Claudeと CSS と東京の AI 調達"}'
    )

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["standfirst"] == "今朝の3本。静かな朝の観察。"
    assert result["daily_title"] == "Claudeと CSS と東京の AI 調達"
    # Claude 呼び出しは正確に 1 回。
    assert fake_client.messages.create.call_count == 1


def test_generate_edition_meta_strips_code_fence_around_json() -> None:
    """Claude がコードブロックで JSON を囲んでも parse できる。"""
    fake_client = _make_fake_anthropic(
        '```json\n'
        '{"standfirst": "今朝の3本。静かに観察する。", '
        '"daily_title": "観察的見出し"}\n'
        '```'
    )

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["standfirst"] == "今朝の3本。静かに観察する。"
    assert result["daily_title"] == "観察的見出し"


# ── 異常系: JSON parse 失敗 → フォールバック ─────────────────────────────


def test_generate_edition_meta_falls_back_on_invalid_json() -> None:
    fake_client = _make_fake_anthropic("これは JSON ではありません。")

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["standfirst"] == f"今朝の{len(SAMPLE_ARTICLES)}本。"
    assert result["daily_title"] == " / ".join(
        a["title"] for a in SAMPLE_ARTICLES
    )


def test_generate_edition_meta_falls_back_on_partially_valid_json() -> None:
    """JSON っぽいが key が欠けている場合もフォールバック。"""
    fake_client = _make_fake_anthropic('{"standfirst": "今朝の3本。"}')

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["standfirst"] == f"今朝の{len(SAMPLE_ARTICLES)}本。"
    assert result["daily_title"] == " / ".join(
        a["title"] for a in SAMPLE_ARTICLES
    )


def test_generate_edition_meta_falls_back_on_wrong_field_types() -> None:
    """standfirst が int 等で str ではない場合もフォールバック。"""
    fake_client = _make_fake_anthropic(
        '{"standfirst": 123, "daily_title": "title"}'
    )

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["standfirst"] == f"今朝の{len(SAMPLE_ARTICLES)}本。"
    assert result["daily_title"] == " / ".join(
        a["title"] for a in SAMPLE_ARTICLES
    )


def test_generate_edition_meta_falls_back_on_empty_strings() -> None:
    """値が空文字なら、フォールバックを使う。"""
    fake_client = _make_fake_anthropic(
        '{"standfirst": "  ", "daily_title": ""}'
    )

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["standfirst"] == f"今朝の{len(SAMPLE_ARTICLES)}本。"
    assert result["daily_title"] == " / ".join(
        a["title"] for a in SAMPLE_ARTICLES
    )


# ── 異常系: Claude API 例外 → フォールバック ─────────────────────────────


def test_generate_edition_meta_falls_back_on_claude_exception() -> None:
    fake_client = _make_failing_anthropic(RuntimeError("timeout"))

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["standfirst"] == f"今朝の{len(SAMPLE_ARTICLES)}本。"
    assert result["daily_title"] == " / ".join(
        a["title"] for a in SAMPLE_ARTICLES
    )
    # 例外でもリトライしない (1 回のみ)。Claude quota 浪費防止。
    assert fake_client.messages.create.call_count == 1


# ── 境界: articles が空 ────────────────────────────────────────────────


def test_generate_edition_meta_handles_empty_articles() -> None:
    """空 articles の場合、Claude を呼ばずに固定値を返す。"""
    fake_client = MagicMock()

    result = daily_news.generate_edition_meta(fake_client, [])

    assert result["standfirst"] == "今朝の0本。"
    assert result["daily_title"] == ""
    fake_client.messages.create.assert_not_called()


# ── 後処理ガード: 禁止ワード / 絵文字は warn のみで通す ───────────────


def test_generate_edition_meta_warns_on_banned_word_but_passes_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_client = _make_fake_anthropic(
        '{"standfirst": "今朝の3本。やばい一日だった。", '
        '"daily_title": "驚愕の AI 動向"}'
    )
    caplog.set_level(logging.WARNING, logger="daily_news")

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    # 値はそのまま通す (block しない)。
    assert result["standfirst"] == "今朝の3本。やばい一日だった。"
    assert result["daily_title"] == "驚愕の AI 動向"
    # warning は 2 件以上出ている。
    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "banned word" in r.getMessage()
    ]
    assert len(warning_records) >= 2


def test_generate_edition_meta_warns_on_emoji_but_passes_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_client = _make_fake_anthropic(
        '{"standfirst": "今朝の3本。静かな観察。", '
        '"daily_title": "AIニュース\\u2705"}'
    )
    caplog.set_level(logging.WARNING, logger="daily_news")

    result = daily_news.generate_edition_meta(fake_client, SAMPLE_ARTICLES)

    assert result["daily_title"] == "AIニュース✅"
    emoji_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "emoji" in r.getMessage()
    ]
    assert len(emoji_warnings) >= 1


# ── 契約: 戻り値は dict[str, str] のキー ────────────────────────────────


def test_generate_edition_meta_return_shape_contract() -> None:
    """常に dict で "standfirst" / "daily_title" の 2 キーのみ。"""
    fake_client: Callable[[str], MagicMock] = _make_fake_anthropic
    for text in (
        '{"standfirst": "今朝の3本。", "daily_title": "t"}',
        "not json",
        '{"standfirst": "今朝の3本。"}',
    ):
        result = daily_news.generate_edition_meta(
            fake_client(text), SAMPLE_ARTICLES
        )
        assert set(result.keys()) == {"standfirst", "daily_title"}
        assert isinstance(result["standfirst"], str)
        assert isinstance(result["daily_title"], str)
