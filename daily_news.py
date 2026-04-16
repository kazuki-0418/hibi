"""
Personal AI Newspaper — Phase 1 Minimum Viable Version
Fetches recent YouTube videos → summarizes with Claude → sends Gmail.
"""

import os
import base64
import sys
from email.mime.text import MIMEText
from datetime import datetime, timezone

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from youtube_transcript_api import YouTubeTranscriptApi
from anthropic import Anthropic


# ============================================================
# CONFIG
# ============================================================
YOUTUBE_CHANNELS = [
    ("Theo - t3.gg", "UCbRP3c757lWg9M-U7TyEkXA"),
    ("AI Explained", "UCNJ1Ymd5yFuUPtn21xtRbbw"),
    ("Fireship", "UCsBjURrPoezykLs9EqgamOA"),
]

VIDEOS_PER_CHANNEL = 3
CLAUDE_MODEL = "claude-sonnet-4-6"
TRANSCRIPT_CHAR_LIMIT = 15000  # コスト制御

RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")


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
            }
        )
    return videos


# ============================================================
# 2. Transcript fetch (free, via scraping)
# ============================================================
def get_transcript(video_id: str) -> str | None:
    """Returns None if transcript unavailable."""
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=["en", "ja"])
        # fetched は FetchedTranscript オブジェクト。snippets 属性に各行
        return " ".join([snippet.text for snippet in fetched.snippets])
    except Exception as e:
        print(f"    [skip] transcript unavailable: {type(e).__name__}: {e}")
        return None


# ============================================================
# 3. Claude summarize
# ============================================================
def summarize(client: Anthropic, title: str, transcript: str) -> str:
    prompt = f"""以下のYouTube動画を日本語で3行に要約してください。
技術的な要点、実装のヒント、開発者にとっての示唆を優先してください。
各行は1文で、「・」で始めてください。

タイトル: {title}

字幕:
{transcript[:TRANSCRIPT_CHAR_LIMIT]}

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
        html += f'<h2 style="border-bottom:2px solid #333;padding-bottom:4px;margin-top:32px;">{section["channel"]}</h2>'
        for v in section["videos"]:
            summary_html = v["summary"].replace("\n", "<br>")
            html += f"""
<div style="margin:16px 0;padding:12px 16px;background:#f7f7f7;border-radius:8px;">
  <h3 style="margin:0 0 8px 0;font-size:16px;">
    <a href="{v['url']}" style="color:#1a73e8;text-decoration:none;">{v['title']}</a>
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
    if not RECIPIENT_EMAIL:
        print("❌ RECIPIENT_EMAIL env var not set")
        sys.exit(1)

    youtube = build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])
    claude = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    sections = []
    for channel_name, channel_id in YOUTUBE_CHANNELS:
        print(f"\n📺 {channel_name}")
        videos = fetch_recent_videos(youtube, channel_id, VIDEOS_PER_CHANNEL)

        processed = []
        for v in videos:
            print(f"  • {v['title'][:70]}")
            transcript = get_transcript(v["video_id"])
            if not transcript:
                continue
            summary = summarize(claude, v["title"], transcript)
            processed.append(
                {
                    "title": v["title"],
                    "summary": summary,
                    "url": f"https://www.youtube.com/watch?v={v['video_id']}",
                }
            )

        if processed:
            sections.append({"channel": channel_name, "videos": processed})

    if not sections:
        print("\n⚠️  No content to send today.")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html = build_email_html(sections)
    send_email(
        subject=f"📰 Daily News — {today}",
        html_body=html,
        to=RECIPIENT_EMAIL,
    )


if __name__ == "__main__":
    main()
