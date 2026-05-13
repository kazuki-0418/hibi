"""
Personal AI Newspaper — Phase 2 multi-source edition.
Fetches YouTube uploads + RSS articles → summarizes with Claude → sends Gmail.
"""

import base64
import hashlib
import hmac
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from urllib.parse import quote

import sentry_sdk
import yaml
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig
from anthropic import Anthropic

from db import (
    get_conn,
    get_or_create_edition_for_today,
    is_already_sent,
    save_article,
    update_edition_sources_scanned,
)
from fetchers import rss as rss_fetcher
from fetchers import youtube as youtube_fetcher
from mailer import build_html as build_hibi_html
from observability import init_sentry_from_env
from ranking import compute_interest_centroid, cosine_similarity, count_recent_clicks
from send_mail import format_subject
from voice import check_voice_violations

log = logging.getLogger(__name__)

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
EMBEDDING_MODEL = "text-embedding-3-small"  # OpenAI; 1536 dim。差し替える時は 003 migration も見直す

# --- Personalization ranking (#28) ---
# 当面 kazuki 1人運用。多人数化するなら env で渡して上書きする。
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
RANKING_WINDOW_DAYS = 30
COLD_START_CLICKS = 5       # これ未満なら centroid を無視して純ランダム
FULL_WEIGHT_CLICKS = 30     # これ以上で centroid を full weight で適用
# weight=1 時: score = sim * SIM_BASE + rand() * JITTER_BASE
# weight=0 時: score = rand() * (SIM_BASE + JITTER_BASE)（= 実質ランダム）
SIM_BASE = 0.7
JITTER_BASE = 0.3
# 候補メタデータ本文は fetch 済みだが長い。ranking 用の埋め込み入力は頭を切って
# cost を抑える（1候補 ≒ 600 tokens になるのが目安）
RANKING_DESC_CHAR_LIMIT = 500
RANKING_TOP_LOG = 10

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
# OpenAI embedding
# ============================================================
# 本文ではなく title + summary で埋め込む。理由: 配信時に既に圧縮済みの内容で
# 「読みたい」と判断しているので、クリック→類似ランキングの学習信号としては
# title+summary の方が人間の判断面に近い。本文で埋めると「読まなかった部分」
# も学習信号に混じる。
def _get_openai_client():
    """OPENAI_API_KEY が未設定の環境では None を返す（embedding 無効化）。"""
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI()


def embed_article(openai_client, title: str, summary: str) -> list[float] | None:
    if openai_client is None:
        return None
    try:
        resp = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=f"{title}\n\n{summary}",
        )
        return resp.data[0].embedding
    except Exception as e:
        print(f"  ⚠️ embedding failed: {e}")
        return None


def embed_batch(openai_client, texts: list[str]) -> list[list[float] | None]:
    """ランキング用に候補を一括埋め込み。OpenAI 失敗時は None で揃える。"""
    if openai_client is None or not texts:
        return [None] * len(texts)
    try:
        resp = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
        return [d.embedding for d in resp.data]
    except Exception as e:
        print(f"  ⚠️ batch embedding failed: {e}")
        return [None] * len(texts)


# ============================================================
# Claude summarize
# ============================================================
def summarize(client: Anthropic, title: str, content: str) -> str:
    # design-system/README.md "Content fundamentals → Voice" 由来。
    # 具体的な禁止ワード列挙ではなく原則だけを 5-7 行で示し、
    # post-processing (`check_voice_violations`) で観測する設計。
    voice_rule = """あなたは新聞 Hibi の編集者として要約を書きます。文体ルール:
- 三人称・観察的・宣言的に書く。新聞は報告するのであって売り込まない。
- 一人称(「私」「僕」)も二人称呼びかけ(「あなた」「読者の皆様」)も使わない。
- 賞賛は抑制する。「すごい」「最高」より「興味深い」「注目」。
- 感嘆符(「!」「！」)、絵文字、絵文字的記号は使わない。
- マーケティング的な煽り(「今すぐ」「お見逃しなく」「驚愕」「衝撃」)を避ける。
- 句点「。」で終える事実の記述を基本とする。"""

    prompt = f"""{voice_rule}

以下の記事/動画を日本語で3行に要約してください。
技術的な要点、実装のヒント、開発者にとっての示唆を優先してください。
各行は1文で、「・」で始めてください。

重要: 本文が断片的・不十分・要約困難な場合でも、謝罪文・「情報が不足」等の注釈・推測による補完は絶対に禁止。その場合は何も出力せず空文字列のみ返してください。

タイトル: {title}

本文:
{content[:CONTENT_CHAR_LIMIT]}

出力形式:
・(1行目)
・(2行目)
・(3行目)"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    summary = response.content[0].text.strip()

    # design-system voice & tone への準拠を観測する。違反があっても配信は
    # 止めず warning ログのみ。意図は voice.py module docstring を参照。
    if summary:
        violations = check_voice_violations(summary)
        if violations:
            log.warning("voice violations in summary: %s", violations)

    return summary


# ============================================================
# Click-tracking URL rewrite
# ============================================================
# HMAC signer kept IN SYNC with service/app/signing.py. The golden vector in
# service/tests/test_signing.py is the contract — if you edit this, verify
# it still produces the expected output there.
_CLICK_SIG_LEN = 22


def _sign_article(article_id: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), article_id.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode()[:_CLICK_SIG_LEN]


def _redirect_url(article_id: str | None, original_url: str) -> str:
    """Return the tracking URL for an article, or the original URL if tracking
    is not configured yet (missing env) or the article id is unavailable.

    This is intentionally lenient: a new deploy may not have CLICK_SIGNING_SECRET
    / PUBLIC_BASE_URL set. In that case, the email still works — just without
    click tracking — rather than 404'ing every link.
    """
    secret = os.environ.get("CLICK_SIGNING_SECRET")
    base = os.environ.get("PUBLIC_BASE_URL")
    if not article_id or not secret or not base:
        return original_url
    sig = _sign_article(article_id, secret)
    return f"{base.rstrip('/')}/r/{quote(article_id, safe='')}?s={quote(sig, safe='')}"


# ============================================================
# Build HTML email (Hibi design-system; see `mailer.build_html`)
# ============================================================
def _sections_to_articles(sections: list[dict]) -> list[dict]:
    """Flatten `sections` (grouped by source) into the flat `articles` shape
    `mailer.build_html` expects, applying the click-tracking redirect to
    each URL so signed `/r/<id>` links survive the new template.
    """
    articles: list[dict] = []
    for section in sections:
        source_name = section["source_name"]
        for item in section["items"]:
            articles.append({
                "title": item["title"],
                "url": _redirect_url(item.get("article_id"), item["url"]),
                "summary": item["summary"],
                "source": source_name,
                # category / source_type / learning / practical_application:
                # not surfaced by daily_news pipeline yet; `_story_html`
                # handles their absence gracefully.
            })
    return articles


# ============================================================
# Personalization ranking (#28)
# ============================================================
def rank_candidates(
    candidates: list[dict],
    user_id: str,
    openai_client,
) -> list[dict]:
    """候補を click-history ベースの similarity + jitter で並べ替える。

    - 履歴 < COLD_START_CLICKS or centroid None → 完全ランダム（従来挙動）
    - 5 ≦ clicks < 30 → centroid を linearly interpolate（clicks/30）
    - clicks ≥ FULL_WEIGHT_CLICKS → full weight で centroid を使う

    Returns 元の list と同じ件数、score 降順。各候補に 'sim' / 'score' が
    書き込まれる。side effect で top-N を stdout にログ出力する。
    """
    with get_conn() as conn:
        click_count = count_recent_clicks(conn, user_id, RANKING_WINDOW_DAYS)
        centroid = (
            compute_interest_centroid(conn, user_id, RANKING_WINDOW_DAYS)
            if click_count >= COLD_START_CLICKS
            else None
        )

    if centroid is None:
        print(
            f"🎲 Cold start ({click_count} recent clicks, threshold={COLD_START_CLICKS}) "
            "— using random ranking"
        )
        random.shuffle(candidates)
        return candidates

    # 候補を1回の OpenAI 呼び出しでまとめて埋め込む
    texts = [
        f"{c.get('title', '')}\n\n{(c.get('description') or '')[:RANKING_DESC_CHAR_LIMIT]}"
        for c in candidates
    ]
    vectors = embed_batch(openai_client, texts)

    weight = min(1.0, click_count / FULL_WEIGHT_CLICKS)
    for c, vec in zip(candidates, vectors):
        if vec is None:
            c["sim"] = 0.0
        else:
            c["sim"] = cosine_similarity(vec, centroid)
        # sim を信じる度合いは weight に比例。weight=1 で 0.7*sim + 0.3*rand、
        # weight=0 で 1.0*rand に縮退する（= ほぼランダム）
        c["score"] = c["sim"] * SIM_BASE * weight + random.random() * (
            1.0 - (SIM_BASE - JITTER_BASE) * weight
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)

    print(
        f"\n📊 Ranked {len(candidates)} candidates "
        f"(click_count={click_count}, weight={weight:.2f})"
    )
    for i, c in enumerate(candidates[:RANKING_TOP_LOG], 1):
        title = (c.get("title") or "")[:60]
        sim = c.get("sim", 0.0)
        score = c.get("score", 0.0)
        print(
            f"  [rank {i:2d}] sim={sim:.2f} score={score:.2f}  "
            f"{c.get('source_name', '?')} / {title}"
        )
    if len(candidates) > RANKING_TOP_LOG:
        print(f"  [skipped pool] {len(candidates) - RANKING_TOP_LOG} candidates below rank {RANKING_TOP_LOG}")

    return candidates


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
    openai_client = _get_openai_client()
    if openai_client is None:
        print("⚠️  OPENAI_API_KEY not set — saving articles without embeddings")
    ytt_api = YouTubeTranscriptApi(
        proxy_config=WebshareProxyConfig(
            proxy_username=os.environ["WEBSHARE_USERNAME"],
            proxy_password=os.environ["WEBSHARE_PASSWORD"],
        )
    )

    # 今朝の edition 行を確保。articles.edition_id が NOT NULL (migration 005)
    # なので save_article 呼び出し前に必ず取る。再実行された場合は同じ
    # issue_no を再利用する (editions.date UNIQUE)。
    edition_issue_no = get_or_create_edition_for_today()
    print(f"📰 Edition: issue_no={edition_issue_no}")

    # Stage A: 全ソースからメタデータのみ取得（本文/要約なし）
    # `sources_scanned` は #52 で editions に保存。fetched_count は取得試行数
    # (14日窓 / unsent フィルタ前)。fetch 自体が例外で落ちた場合は error 文字列
    # を 200 文字で打ち切って残す。
    print("🔎 Gathering candidates (metadata only)...")
    candidates: list[dict] = []
    sources_scanned: list[dict] = []
    for source in sources:
        source_name = source["name"]
        source_kind = "YouTube" if source["type"] == "youtube" else "RSS"
        try:
            items = _fetch_items(source, youtube_client, METADATA_PER_SOURCE)
            entry: dict = {
                "name": source_name,
                "kind": source_kind,
                "fetched_count": len(items),
            }
        except Exception as exc:
            items = []
            entry = {
                "name": source_name,
                "kind": source_kind,
                "fetched_count": 0,
                "error": str(exc)[:200],
            }
        sources_scanned.append(entry)

        fresh = [i for i in items if _is_within_lookback(i["published_at"])]
        unsent = [i for i in fresh if not is_already_sent(i["content_id"])]
        candidates.extend(unsent)
        suffix = f", error: {entry['error']}" if entry.get("error") else ""
        print(
            f"  📡 [{source['type']}] {source_name}: {len(items)} fetched, "
            f"{len(fresh)} within {MAX_LOOKBACK_DAYS}d, {len(unsent)} unsent{suffix}"
        )

    # Stage A 完了時点で sources_scanned は確定するので editions に書き戻す。
    # 配信が後段で失敗しても透明性ログは残る (= 何をスキャンしたかの記録)。
    update_edition_sources_scanned(edition_issue_no, sources_scanned)

    print(f"\n📊 Total unsent candidates: {len(candidates)}")

    # Stage B: personalization ranking + attempt_pool 抽出（#28）。
    # rank_candidates は cold start 時に random.shuffle にフォールバックする。
    ranked = rank_candidates(candidates, DEFAULT_USER_ID, openai_client)
    attempt_pool = ranked[:MAX_ATTEMPTS]
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

        summary = summarize(claude, item["title"], content)
        if not summary or len(summary) < MIN_SUMMARY_CHARS:
            print(
                "  → skip (summary empty: Claude defended against insufficient content)"
            )
            skipped_count += 1
            continue

        summarized_count += 1
        print(f"  ✅ summarized ({summarized_count}/{MAX_VIDEOS_PER_RUN})")

        # 送信失敗時に再送できるよう、保存は送信前に行う。
        # article_id はクリック追跡 URL (/r/{id}) の生成に使う。
        embedding = embed_article(openai_client, item["title"], summary)
        article_id = save_article(
            {
                "source_type": item["source_type"],
                "source_name": item["source_name"],
                "content_id": item["content_id"],
                "title": item["title"],
                "url": item["url"],
                "summary": summary,
                "category": item.get("category"),
                "embedding": embedding,
                "embedding_model": EMBEDDING_MODEL if embedding is not None else None,
            },
            edition_id=edition_issue_no,
        )

        processed_by_source.setdefault(item["source_name"], []).append(
            {
                "title": item["title"],
                "summary": summary,
                "url": item["url"],
                "article_id": article_id,
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

    # sources.yaml の順序で section を組み立てる
    sections = [
        {"source_name": s["name"], "items": processed_by_source[s["name"]]}
        for s in sources
        if s["name"] in processed_by_source
    ]

    if not sections:
        print("\n⚠️  No content to send today.")
        return

    date_str = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    articles = _sections_to_articles(sections)
    # スキップ件数を footer で透明性表示する (#12 Phase 1)。
    # 字幕不足 / Claude による短文 reject の合計。詳細区別は今回はしない。
    html = build_hibi_html(articles, date_str, skipped_count=skipped_count)
    send_email(
        subject=format_subject(date_str, count=len(articles)),
        html_body=html,
        to=recipient,
    )


if __name__ == "__main__":
    sentry_active = init_sentry_from_env()
    try:
        main()
    except Exception:
        # Make sure Sentry captures the error before the GitHub Actions
        # runner tears the process down. Re-raise so the workflow still
        # fails (existing failure-email path stays intact).
        if sentry_active:
            sentry_sdk.capture_exception()
        raise
    finally:
        if sentry_active:
            # Flush is critical for short-lived processes (cron jobs);
            # without it, async transport may drop events on exit.
            sentry_sdk.flush(timeout=5)
