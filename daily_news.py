"""
Personal AI Newspaper — Phase 2 multi-source edition.
Fetches YouTube uploads + RSS articles → summarizes with Claude → sends Gmail.
"""

import html as html_lib
import os
import base64
import random
import sys
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

import yaml
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
from anthropic import Anthropic

# ローカル実行用に .env を読み込む。Actions 上では .env が無く no-op。
# 既存の環境変数（Actions の secrets 含む）は上書きしない。
load_dotenv()

from db import is_already_sent, save_article
from fetchers import rss as rss_fetcher
from fetchers import youtube as youtube_fetcher

# ============================================================
# CONFIG
# ============================================================
METADATA_PER_SOURCE = 15  # Stage A で各ソースから取得するメタデータ件数
MAX_LOOKBACK_DAYS = 14  # 2週間より古いアイテムは配信対象外
MAX_VIDEOS_PER_RUN = 5  # 1回の配信で要約・送信する最大本数（目標値）
MAX_ATTEMPTS = 30  # 1回の実行で試行する最大候補数（無限試行防止）
MIN_CONTENT_CHARS = 500  # transcript/記事本文がこれ未満なら失敗扱い
MIN_SUMMARY_CHARS = 10  # Claude が防御プロンプトに従って空を返したケースを弾く閾値
CLAUDE_MODEL = "claude-sonnet-4-6"
CONTENT_CHAR_LIMIT = 15000  # Claude に渡す本文の上限（コスト制御）
DEFAULT_PRIORITY = 2  # sources.yaml に priority が無い場合のデフォルト

# ソース category slug → メール内で表示するラベル
CATEGORY_LABELS = {
    "tech": "Tech",
    "tech-news": "Tech News",
    "startup": "Startup",
    "dev-for-startup": "Dev for Startup",
    "senior-engineer": "Senior Engineer",
    "indie-hacker": "Indie Hacker",
    "career": "Career",
    "productivity": "Productivity",
    "podcast": "Podcast",
    "marketing": "Marketing",
    "gadget": "Gadget",
}

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


def _load_sources(path: str = "sources.yaml") -> list[dict]:
    with open(path) as f:
        config = yaml.safe_load(f)
    return [s for s in config["sources"] if s.get("enabled", True)]


def _category_label(category: str | None) -> str:
    if not category:
        return ""
    return CATEGORY_LABELS.get(category, category.replace("-", " ").title())


def _stars(priority: int) -> str:
    prio = max(1, min(3, int(priority or DEFAULT_PRIORITY)))
    return "★" * prio


def _fetch_items(
    source: dict, youtube_client, max_results: int
) -> list[dict]:
    stype = source["type"]
    if stype == "youtube":
        return youtube_fetcher.fetch_recent_items(
            youtube_client, source, max_results
        )
    if stype == "rss":
        return rss_fetcher.fetch_recent_items(source, max_results)
    print(f"  ⚠️  Unknown source type '{stype}' ({source['name']}), skipping")
    return []


def _fetch_content(item: dict, ytt_api: YouTubeTranscriptApi) -> str | None:
    stype = item["source_type"]
    if stype == "youtube":
        return youtube_fetcher.get_content_text(ytt_api, item)
    if stype == "rss":
        return rss_fetcher.get_content_text(item)
    return None


# ============================================================
# Claude summarize
# ============================================================
_DEFENSIVE_DIRECTIVE = (
    "重要: 本文が断片的・不十分・要約困難な場合でも、謝罪文・"
    "「情報が不足」等の注釈・推測による補完は絶対に禁止。"
    "その場合は何も出力せず空文字列のみ返してください。"
)


def summarize_video(client: Anthropic, title: str, transcript: str) -> str:
    prompt = f"""以下のYouTube動画を日本語で3行に要約してください。
技術的な要点、実装のヒント、開発者にとっての示唆を優先してください。
各行は1文で、「・」で始めてください。

{_DEFENSIVE_DIRECTIVE}

タイトル: {title}

字幕:
{transcript[:CONTENT_CHAR_LIMIT]}

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


def summarize_article(client: Anthropic, title: str, body: str) -> str:
    prompt = f"""以下のニュース記事を日本語で3セクションに要約してください。
開発者・indie hacker の視点から「事実 → 学び → 行動」の流れで構成してください。

{_DEFENSIVE_DIRECTIVE}

タイトル: {title}

本文:
{body[:CONTENT_CHAR_LIMIT]}

出力形式（各セクションは見出しのみの行、本文は 2〜3 文、セクション間は空行 1 つ）:

概要
(事実ベースで何が起きたか/何が発表されたかを 2〜3 文)

学べること
(読者が得られる示唆・背景知識を 2〜3 文)

実践的な応用
(具体的なアクション・検討すべき事項を 2〜3 文)"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def summarize(
    client: Anthropic, item: dict, content: str
) -> str:
    """Dispatch to the right summarizer based on source_type."""
    if item["source_type"] == "rss":
        return summarize_article(client, item["title"], content)
    return summarize_video(client, item["title"], content)


_ARTICLE_HEADERS = {
    "概要": "overview",
    "学べること": "lessons",
    "実践的な応用": "actions",
}


def parse_article_summary(summary: str) -> dict[str, str] | None:
    """Split a 3-section article summary into {overview, lessons, actions}.

    Returns ``None`` if any section is missing or empty — caller should treat
    that as a defensive-return from Claude and skip the item.
    """
    parts = {"overview": "", "lessons": "", "actions": ""}
    current: str | None = None
    buf: list[str] = []

    for raw in summary.splitlines():
        stripped = raw.strip().rstrip("：:").strip()
        if stripped in _ARTICLE_HEADERS:
            if current:
                parts[current] = "\n".join(buf).strip()
            current = _ARTICLE_HEADERS[stripped]
            buf = []
            continue
        buf.append(raw)
    if current:
        parts[current] = "\n".join(buf).strip()

    if not all(parts.values()):
        return None
    return parts


# ============================================================
# Build HTML email
# ============================================================
def _render_video_item(item: dict) -> str:
    title = html_lib.escape(item["title"])
    url = html_lib.escape(item["url"])
    summary_html = html_lib.escape(item["summary"]).replace("\n", "<br>")
    return f"""
<div style="margin:16px 0;padding:12px 16px;background:#f7f7f7;border-radius:8px;">
  <h3 style="margin:0 0 8px 0;font-size:16px;">
    <a href="{url}" style="color:#1a73e8;text-decoration:none;">{title}</a>
  </h3>
  <div style="color:#444;line-height:1.6;font-size:14px;">{summary_html}</div>
  <div style="margin-top:10px;font-size:13px;">
    <a href="{url}" style="color:#1a73e8;text-decoration:none;">→ 動画を見る</a>
  </div>
</div>
"""


def _render_article_item(item: dict) -> str:
    title = html_lib.escape(item["title"])
    url = html_lib.escape(item["url"])
    parts = item.get("summary_parts") or {}

    def _section(label: str, text: str) -> str:
        escaped = html_lib.escape(text).replace("\n", "<br>")
        return (
            f'<div style="margin-top:10px;">'
            f'<div style="font-weight:600;color:#222;font-size:13px;letter-spacing:.02em;">{label}</div>'
            f'<div style="color:#444;line-height:1.6;font-size:14px;margin-top:2px;">{escaped}</div>'
            f"</div>"
        )

    body = (
        _section("概要", parts.get("overview", ""))
        + _section("学べること", parts.get("lessons", ""))
        + _section("実践的な応用", parts.get("actions", ""))
    )
    return f"""
<div style="margin:16px 0;padding:12px 16px;background:#f7f7f7;border-radius:8px;">
  <h3 style="margin:0 0 8px 0;font-size:16px;">
    <a href="{url}" style="color:#1a73e8;text-decoration:none;">{title}</a>
  </h3>
  {body}
  <div style="margin-top:12px;font-size:13px;">
    <a href="{url}" style="color:#1a73e8;text-decoration:none;">→ ソースを読む</a>
  </div>
</div>
"""


def build_email_html(sections: list[dict]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:640px;margin:0 auto;padding:16px;color:#222;">
<h1 style="margin:0 0 4px 0;">📰 Personal AI Newspaper</h1>
<p style="color:#888;margin:0 0 24px 0;">{today}</p>
"""
    for section in sections:
        label = html_lib.escape(_category_label(section.get("category")))
        source_name = html_lib.escape(section["source_name"])
        stars = _stars(section.get("priority", DEFAULT_PRIORITY))
        header = (
            f"{label} <span style=\"color:#f5a623;margin-left:8px;\">{stars}</span>"
            if label
            else f"<span style=\"color:#f5a623;\">{stars}</span>"
        )
        html += (
            f'<h2 style="border-bottom:2px solid #333;padding-bottom:4px;'
            f'margin-top:32px;font-size:15px;letter-spacing:.03em;">{header}</h2>'
            f'<div style="color:#888;font-size:12px;margin:4px 0 0 0;">{source_name}</div>'
        )
        for item in section["items"]:
            if item["source_type"] == "rss":
                html += _render_article_item(item)
            else:
                html += _render_video_item(item)
    html += "</body></html>"
    return html


# ============================================================
# Gmail send
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

    sources = _load_sources()
    recipient = os.environ["RECIPIENT_EMAIL"]

    youtube_client = build(
        "youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"]
    )
    claude = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    ytt_api = YouTubeTranscriptApi(
        proxy_config=WebshareProxyConfig(
            proxy_username=os.environ["WEBSHARE_USERNAME"],
            proxy_password=os.environ["WEBSHARE_PASSWORD"],
        )
    )

    # Stage A: 全ソースからメタデータのみ取得（本文/要約なし）
    print("🔎 Gathering candidates (metadata only)...")
    candidates: list[dict] = []
    for source in sources:
        items = _fetch_items(source, youtube_client, METADATA_PER_SOURCE)
        fresh = [i for i in items if _is_within_lookback(i["published_at"])]
        unsent = [i for i in fresh if not is_already_sent(i["content_id"])]
        candidates.extend(unsent)
        print(
            f"  📡 [{source['type']}] {source['name']}: {len(items)} fetched, "
            f"{len(fresh)} within {MAX_LOOKBACK_DAYS}d, {len(unsent)} unsent"
        )

    print(f"\n📊 Total unsent candidates: {len(candidates)}")

    # Stage B: 全候補をシャッフルし、先頭から MAX_ATTEMPTS 本を試行プールに
    random.shuffle(candidates)
    attempt_pool = candidates[:MAX_ATTEMPTS]
    print(
        f"🎲 Attempt pool: {len(attempt_pool)} items "
        f"(target: {MAX_VIDEOS_PER_RUN} summaries, cap: {MAX_ATTEMPTS} attempts)"
    )

    if not attempt_pool:
        print("\n⚠️  No content to send today.")
        return

    # Stage C: 試行プールを順に処理。MAX_VIDEOS_PER_RUN 本揃ったら break
    processed_by_source: dict[str, list[dict]] = {}
    summarized_count = 0
    skipped_count = 0

    for idx, item in enumerate(attempt_pool, 1):
        print(
            f"\n[{idx}/{len(attempt_pool)}] "
            f"[{item['source_type']}:{item['source_name']}] "
            f"{item['title'][:70]}"
        )

        content = _fetch_content(item, ytt_api)
        if not content or len(content) < MIN_CONTENT_CHARS:
            char_count = len(content) if content else 0
            print(
                f"  → skip (content unavailable or too short: {char_count} chars)"
            )
            skipped_count += 1
            continue

        summary = summarize(claude, item, content)
        if not summary or len(summary) < MIN_SUMMARY_CHARS:
            print(
                "  → skip (summary empty: Claude defended against insufficient content)"
            )
            skipped_count += 1
            continue

        summary_parts: dict[str, str] | None = None
        if item["source_type"] == "rss":
            summary_parts = parse_article_summary(summary)
            if summary_parts is None:
                print(
                    "  → skip (article summary missing one or more sections)"
                )
                skipped_count += 1
                continue

        summarized_count += 1
        print(f"  ✅ summarized ({summarized_count}/{MAX_VIDEOS_PER_RUN})")

        processed_by_source.setdefault(item["source_name"], []).append(
            {
                "title": item["title"],
                "url": item["url"],
                "source_type": item["source_type"],
                "summary": summary,
                "summary_parts": summary_parts,
            }
        )

        # 送信失敗時に再送できるよう、保存は送信前に行う
        save_article(
            {
                "source_type": item["source_type"],
                "source_name": item["source_name"],
                "content_id": item["content_id"],
                "title": item["title"],
                "url": item["url"],
                "summary": summary,
            }
        )

        if summarized_count >= MAX_VIDEOS_PER_RUN:
            break

    print(f"\n📈 Result: {summarized_count} summarized, {skipped_count} skipped")
    if summarized_count < MAX_VIDEOS_PER_RUN:
        print(
            f"⚠️  Target was {MAX_VIDEOS_PER_RUN}, got {summarized_count}. "
            "Likely cause: content blocking or low candidate pool."
        )

    # sources.yaml の順序で section を組み立てる。category/priority もここで付与
    sections = []
    for s in sources:
        if s["name"] not in processed_by_source:
            continue
        sections.append(
            {
                "source_name": s["name"],
                "category": s.get("category"),
                "priority": s.get("priority", DEFAULT_PRIORITY),
                "items": processed_by_source[s["name"]],
            }
        )

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
