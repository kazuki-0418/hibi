"""Tests for the shared Gmail sender (`email_sender`).

Issue #140 で `daily_news.send_email` の Gmail OAuth 認証経路を `email_sender`
に抽出した。本テストは ``build_message`` の MIME 構造のみを検証する。
Gmail API 呼び出し / 認証は副作用なので含めない (mock すべきは boundary)。
"""
from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from email_sender import build_message


def test_build_message_html_only_is_single_text_html_part() -> None:
    """``text_body=None`` returns a single text/html part (legacy shape)."""
    msg = build_message(
        subject="Hibi test",
        to="kazuki@example.com",
        html_body="<p>hello</p>",
    )
    assert isinstance(msg, MIMEText)
    assert msg.get_content_type() == "text/html"
    assert msg["subject"] == "Hibi test"
    assert msg["to"] == "kazuki@example.com"
    # HTML body 自体が payload に乗っているはず。
    payload = msg.get_payload(decode=True)
    assert isinstance(payload, bytes)
    assert b"<p>hello</p>" in payload


def test_build_message_multipart_has_plain_then_html() -> None:
    """``text_body`` を渡すと multipart/alternative になり、plain → html
    の順で attach される (RFC 2046: 末尾が「より豊かな表現」)。
    """
    msg = build_message(
        subject="Hibi digest",
        to="kazuki@example.com",
        html_body="<p>こんにちは</p>",
        text_body="こんにちは",
    )
    assert isinstance(msg, MIMEMultipart)
    assert msg.get_content_type() == "multipart/alternative"
    assert msg["subject"] == "Hibi digest"
    assert msg["to"] == "kazuki@example.com"

    parts = msg.get_payload()
    assert isinstance(parts, list)
    assert len(parts) == 2
    plain_part, html_part = parts
    assert isinstance(plain_part, MIMEText)
    assert plain_part.get_content_type() == "text/plain"
    assert isinstance(html_part, MIMEText)
    assert html_part.get_content_type() == "text/html"
    # text/plain が先 (= MUA フォールバック)。
    assert "こんにちは" in plain_part.get_payload(decode=True).decode("utf-8")
    assert "<p>こんにちは</p>" in html_part.get_payload(decode=True).decode(
        "utf-8"
    )


def test_build_message_subject_carries_japanese() -> None:
    """Subject に日本語が乗っても破綻しない (Issue #140 subject 規約)。"""
    subject = "[Hibi] 今週のアイデア候補 5 件 (2026-W21)"
    msg = build_message(
        subject=subject,
        to="kazuki@example.com",
        html_body="<p>x</p>",
        text_body="x",
    )
    # email.header 経由で encode されるが、値の round-trip は subject の中身を
    # 維持していること (Header object 経由でも __str__ で元文字列が戻る)。
    assert subject in str(msg["subject"])
