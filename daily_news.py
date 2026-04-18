"""
Personal AI Newspaper — Phase 1 Minimum Viable Version
Fetches recent YouTube videos → summarizes with Claude → sends Gmail.
"""

import html as html_lib
import os
import base64
import random
import sys
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

import yaml
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
from anthropic import Anthropic

from db import is_already_sent, save_article

# ============================================================
# CONFIG
# ============================================================
METADATA_PER_CHANNEL = 15  # Stage A で取得するメタデータ件数
MAX_LOOKBACK_DAYS = 14  # 2週間より古い動画は配信対象外
MAX_VIDEOS_PER_RUN = 10  # ランダム抽出後、実際に要約・送信する最大本数
CLAUDE_MODEL = "claude-sonnet-4-6"
TRANSCRIPT_CHAR_LIMIT = 15000  # コスト制御

REQUIRED_ENV_VARS = [
    "WEBSHARE_USERNAME",
    "WEBSHARE_PASSWORD",
    "YOUTUBE_API_KEY",
    "ANTHROPIC_API_KEY",
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "RECIPIENT_EMAIL",
    "DATABASE_URL",
]


def _check_env() -> None:
    missing = [k for k in REQUIRED_ENV_VARS if not os.environ.get(k)]
    if missing:
        print(f"❌ Missing env vars: {', '.join(missing)}")
        sys.exit(1)


def _is_within_lookback(published_at_iso: str) -> bool:
    ts = datetime.fromisoformat(published_at_iso.replace("Z", "+00:00"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_LOOKBACK_DAYS)
    return ts >= cutoff


def _load_channels(path: str = "channels.yaml") -> list[tuple[str, str]]:
    with open(path) as f:
        config = yaml.safe_load(f)
    return [
        (c["name"], c["channel_id"])
        for c in config["channels"]
        if c.get("enabled", True)
    ]


# ============================================================
# 1. YouTube fetch (uses 2 units per channel, not 100)
# ============================================================
def fetch_recent_videos(youtube, channel_id: str, max_results: int = 3):
    """Get recent videos via uploads playlist. Costs 2 units/channel."""
    ch = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    if not ch.get("items"):
        print(f"  ⚠️  Channel not found: {channel_id}")
        return []

    uploads_playlist = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = (
        youtube.playlistItems()
        .list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist,
            maxResults=max_results,
        )
        .execute()
    )

    videos = []
    for item in pl.get("items", []):
        videos.append(
            {
                "video_id": item["contentDetails"]["videoId"],
                "title": item["snippet"]["title"],
                "published_at": item["contentDetails"]["videoPublishedAt"],
                "description": item["snippet"].get("description", ""),
            }
        )
    return videos


# ============================================================
# 2. Transcript fetch (free, via scraping)
# ============================================================
def get_transcript(ytt_api: YouTubeTranscriptApi, video_id: str) -> str | None:
    """Returns None if transcript unavailable."""
    try:
        fetched = ytt_api.fetch(video_id, languages=["en", "ja"])
        # fetched は FetchedTranscript オブジェクト。snippets 属性に各行
        return " ".join(snippet.text for snippet in fetched.snippets)
    except Exception as e:
        print(f"    [skip] transcript unavailable: {type(e).__name__}: {e}")
        return None


# ============================================================
# 3. Claude summarize
# ============================================================
def summarize(
    client: Anthropic, title: str, content: str, is_description: bool = False
) -> str:
    source_label = "動画説明文" if is_description else "字幕"
    prompt = f"""以下のYouTube動画を日本語で3行に要約してください。
技術的な要点、実装のヒント、開発者にとっての示唆を優先してください。
各行は1文で、「・」で始めてください。

タイトル: {title}

{source_label}:
{content[:TRANSCRIPT_CHAR_LIMIT]}

出力形式:
・(1行目)
・(2行目)
・(3行目)"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ============================================================
# 4. Build HTML email
# ============================================================
def build_email_html(sections: list[dict]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:640px;margin:0 auto;padding:16px;color:#222;">
<h1 style="margin:0 0 4px 0;">📰 Personal AI Newspaper</h1>
<p style="color:#888;margin:0 0 24px 0;">{today}</p>
"""
    for section in sections:
        channel = html_lib.escape(section["channel"])
        html += f'<h2 style="border-bottom:2px solid #333;padding-bottom:4px;margin-top:32px;">{channel}</h2>'
        for v in section["videos"]:
            title = html_lib.escape(v["title"])
            url = html_lib.escape(v["url"])
            summary_html = html_lib.escape(v["summary"]).replace("\n", "<br>")
            html += f"""
<div style="margin:16px 0;padding:12px 16px;background:#f7f7f7;border-radius:8px;">
  <h3 style="margin:0 0 8px 0;font-size:16px;">
    <a href="{url}" style="color:#1a73e8;text-decoration:none;">{title}</a>
  </h3>
  <div style="color:#444;line-height:1.6;font-size:14px;">{summary_html}</div>
</div>
"""
    html += "</body></html>"
    return html


# ============================================================
# 5. Gmail send
# ============================================================
def send_email(subject: str, html_body: str, to: str):
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEText(html_body, "html")
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"✅ Email sent to {to}")


# ============================================================
# MAIN
# ============================================================
def main():
    _check_env()

    channels = _load_channels()
    recipient = os.environ["RECIPIENT_EMAIL"]

    youtube = build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])
    claude = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ytt_api = YouTubeTranscriptApi(
        proxy_config=WebshareProxyConfig(
            proxy_username=os.environ["WEBSHARE_USERNAME"],  # WebShare のユーザー名
            proxy_password=os.environ["WEBSHARE_PASSWORD"],  # WebShare のパスワード
        )
    )

    # Stage A: 全チャンネルからメタデータのみ取得（transcript/要約なし）
    print("🔎 Gathering candidates (metadata only)...")
    candidates = []
    for channel_name, channel_id in channels:
        videos = fetch_recent_videos(youtube, channel_id, METADATA_PER_CHANNEL)
        fresh = [v for v in videos if _is_within_lookback(v["published_at"])]
        unsent = [v for v in fresh if not is_already_sent(v["video_id"])]
        for v in unsent:
            candidates.append({**v, "channel_name": channel_name})
        print(
            f"  📺 {channel_name}: {len(videos)} fetched, "
            f"{len(fresh)} within {MAX_LOOKBACK_DAYS}d, {len(unsent)} unsent"
        )

    print(f"\n📊 Total unsent candidates: {len(candidates)}")

    # Stage B: ランダム抽出（最大 MAX_VIDEOS_PER_RUN 本）
    sample = random.sample(candidates, min(MAX_VIDEOS_PER_RUN, len(candidates)))
    print(f"🎲 Sampled {len(sample)} videos for this run")

    if not sample:
        print("\n⚠️  No content to send today.")
        return

    # Stage C: サンプル分だけ transcript + Claude 要約 + Neon 保存
    processed_by_channel: dict[str, list[dict]] = {}
    for v in sample:
        print(f"\n  • [{v['channel_name']}] {v['title'][:70]}")
        transcript = get_transcript(ytt_api, v["video_id"])

        if transcript:
            content, is_description = transcript, False
        elif v.get("description", "").strip():
            print(f"    → transcript blocked, falling back to description")
            content, is_description = v["description"], True
        else:
            print(f"    → no transcript or description, skipping")
            continue

        summary = summarize(
            claude, v["title"], content, is_description=is_description
        )
        url = f"https://www.youtube.com/watch?v={v['video_id']}"
        processed_by_channel.setdefault(v["channel_name"], []).append(
            {"title": v["title"], "summary": summary, "url": url}
        )

        # 送信失敗時に再送できるよう、保存は送信前に行う
        save_article(
            {
                "source_type": "youtube",
                "source_name": v["channel_name"],
                "content_id": v["video_id"],
                "title": v["title"],
                "url": url,
                "summary": summary,
            }
        )

    # channels.yaml の順序で section を組み立てる
    sections = [
        {"channel": name, "videos": processed_by_channel[name]}
        for name, _ in channels
        if name in processed_by_channel
    ]

    if not sections:
        print("\n⚠️  No content to send today.")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html = build_email_html(sections)
    send_email(
        subject=f"📰 Daily News — {today}",
        html_body=html,
        to=recipient,
    )


if __name__ == "__main__":
    main()
