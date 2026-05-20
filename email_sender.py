"""Shared Gmail OAuth2 email sender.

`daily_news.send_email` と `idea_mining.digest.send_email` の両方が利用する
共通モジュール。OAuth2 refresh_token を使う認証経路 (existing scope:
`https://www.googleapis.com/auth/gmail.send`) を 1 箇所に集約し、HTML 単体 /
HTML+plain text multipart のどちらでも構築できるようにする。

スコープ追加は **行わない** (Issue #140 stop_condition)。configuration は
``GMAIL_CLIENT_ID`` / ``GMAIL_CLIENT_SECRET`` / ``GMAIL_REFRESH_TOKEN`` の
3 環境変数のみ。`RECIPIENT_EMAIL` は呼び出し側で決める。
"""
from __future__ import annotations

import base64
import os
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_message(
    *,
    subject: str,
    to: str,
    html_body: str,
    text_body: str | None = None,
) -> Message:
    """Compose a MIME message for Gmail's `messages.send` API.

    When ``text_body`` is ``None`` the result is a single ``text/html`` part
    (preserves the byte-for-byte shape `daily_news.send_email` historically
    produced). When ``text_body`` is provided, the result is a
    ``multipart/alternative`` with the ``text/plain`` part attached *first*
    so MUAs that prefer plain text get it as the primary body (RFC 2046).
    """
    if text_body is None:
        msg: Message = MIMEText(html_body, "html")
    else:
        multipart = MIMEMultipart("alternative")
        multipart.attach(MIMEText(text_body, "plain"))
        multipart.attach(MIMEText(html_body, "html"))
        msg = multipart
    msg["to"] = to
    msg["subject"] = subject
    return msg


def _build_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=[GMAIL_SEND_SCOPE],
    )
    return build("gmail", "v1", credentials=creds)


def send_email(
    *,
    subject: str,
    to: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    """Send an email through Gmail (OAuth2 refresh_token)."""
    msg = build_message(
        subject=subject, to=to, html_body=html_body, text_body=text_body
    )
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = _build_gmail_service()
    service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
