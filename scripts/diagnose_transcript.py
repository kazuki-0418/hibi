"""WebShare proxy 疎通 + transcript 取得成功率の診断スクリプト。

Issue #18: #17（リトライ方式）の前提検証。
GitHub Actions 上で WebShare proxy が機能しているか、
proxy なし / あり での transcript 成功率を実測する。

本番パイプライン (daily_news.py) からは呼ばれない。手動実行のみ。
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from dataclasses import dataclass
from typing import Optional

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

IP_CHECK_URL = "https://api.ipify.org?format=text"
IP_CHECK_TIMEOUT = 15

# 字幕が確実に存在することが期待できるテスト動画。
# 著作権・センシティブ内容を含まないものを選ぶ。
# 初回ローカル実行で en/ja 字幕の存在を確認済み（または超高確率で存在する大型動画）。
TEST_VIDEOS = [
    ("dQw4w9WgXcQ", "Rick Astley — Never Gonna Give You Up (en 確認済)"),
    ("jNQXAC9IVRw", "Me at the zoo (YouTube 初投稿、en 確認済)"),
    ("hFZFjoX2cGg", "Vue Mastery — Real World Vue (技術系、en 確認済)"),
    ("iG9CE55wbtY", "Ken Robinson TED — Do schools kill creativity? (en+ja 字幕)"),
    ("arj7oStGLkU", "Tim Urban TED — Mind of a master procrastinator (en+ja 字幕)"),
]

# fetch 失敗のうち「動画/チャンネル側起因」のエラー型。
# これらは proxy / IP block と無関係なので、インフラ成功率の計算からは除外する。
INHERENT_ERRORS = {"TranscriptsDisabled", "NoTranscriptFound"}

# 言語フィルタ切り分け用：英語動画 1 本に対する言語パターン
LANG_TEST_VIDEO = ("dQw4w9WgXcQ", "Rick Astley")
LANG_PATTERNS = [["ja"], ["en"], ["en", "ja"]]


@dataclass
class TranscriptResult:
    video_id: str
    label: str
    success: bool
    error_type: Optional[str]
    error_msg: Optional[str]
    transcript_chars: int


def _mask(value: str) -> str:
    """credential を含む文字列をマスクする。"""
    if not value:
        return value
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _scrub_proxy_url(url: str) -> str:
    """proxy URL の credential を伏せる。"""
    # http://user:pass@host:port/ -> http://***:***@host:port/
    return re.sub(r"://[^@]+@", "://***:***@", url)


def _scrub_message(msg: str, secrets: list[str]) -> str:
    out = msg
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    return out


def _section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def check_ip_no_proxy() -> Optional[str]:
    _section("A. egress IP (proxy なし)")
    try:
        resp = requests.get(IP_CHECK_URL, timeout=IP_CHECK_TIMEOUT)
        resp.raise_for_status()
        ip = resp.text.strip()
        print(f"  egress IP: {ip}")
        print("  → GitHub Actions (Azure データセンター帯) のはず")
        return ip
    except Exception as e:
        print(f"  ❌ failed: {type(e).__name__}: {e}")
        return None


def check_ip_with_proxy(
    proxy_url: str, secrets: list[str]
) -> Optional[str]:
    _section("B. egress IP (WebShare proxy 経由)")
    print(f"  proxy: {_scrub_proxy_url(proxy_url)}")
    try:
        resp = requests.get(
            IP_CHECK_URL,
            timeout=IP_CHECK_TIMEOUT,
            proxies={"http": proxy_url, "https": proxy_url},
        )
        resp.raise_for_status()
        ip = resp.text.strip()
        print(f"  egress IP: {ip}")
        print("  → WebShare の IP に変わっていれば proxy 疎通 OK")
        return ip
    except Exception as e:
        msg = _scrub_message(str(e), secrets)
        print(f"  ❌ failed: {type(e).__name__}: {msg}")
        return None


def list_inventory(
    api: YouTubeTranscriptApi,
    video_id: str,
    label: str,
    secrets: list[str],
) -> tuple[Optional[list[tuple[str, bool]]], Optional[str]]:
    """戻り値: (langs, error_type)。langs は (lang_code, is_generated) のリスト。"""
    try:
        tl = api.list(video_id)
        langs = [(t.language_code, t.is_generated) for t in tl]
        return langs, None
    except Exception as e:
        return None, type(e).__name__


def fetch_one(
    api: YouTubeTranscriptApi,
    video_id: str,
    label: str,
    languages: list[str],
    secrets: list[str],
) -> TranscriptResult:
    try:
        fetched = api.fetch(video_id, languages=languages)
        text = " ".join(s.text for s in fetched.snippets)
        return TranscriptResult(
            video_id=video_id,
            label=label,
            success=True,
            error_type=None,
            error_msg=None,
            transcript_chars=len(text),
        )
    except Exception as e:
        return TranscriptResult(
            video_id=video_id,
            label=label,
            success=False,
            error_type=type(e).__name__,
            error_msg=_scrub_message(str(e), secrets)[:300],
            transcript_chars=0,
        )


def run_batch(
    api: YouTubeTranscriptApi,
    videos: list[tuple[str, str]],
    secrets: list[str],
) -> list[TranscriptResult]:
    results: list[TranscriptResult] = []
    for video_id, label in videos:
        print(f"  • [{video_id}] {label}")
        r = fetch_one(api, video_id, label, ["en", "ja"], secrets)
        if r.success:
            print(f"    ✅ ok ({r.transcript_chars} chars)")
        else:
            print(f"    ❌ {r.error_type}: {r.error_msg}")
        results.append(r)
    return results


def summarize(results: list[TranscriptResult], label: str) -> tuple[float, float]:
    """戻り値: (全体成功率, インフラ成功率)。"""
    total = len(results)
    ok = sum(1 for r in results if r.success)
    pct = (ok / total * 100) if total else 0.0

    # インフラ成功率: 動画側起因（TranscriptsDisabled / NoTranscriptFound）を除外して計算
    infra_results = [
        r for r in results if r.success or r.error_type not in INHERENT_ERRORS
    ]
    infra_total = len(infra_results)
    infra_ok = sum(1 for r in infra_results if r.success)
    infra_pct = (infra_ok / infra_total * 100) if infra_total else 0.0

    print(f"  {label}:")
    print(f"    全体    : {ok}/{total} 成功 ({pct:.1f}%)")
    print(
        f"    インフラ: {infra_ok}/{infra_total} 成功 ({infra_pct:.1f}%) "
        f"[動画側失敗 {total - infra_total} 件除外]"
    )
    error_types: dict[str, int] = {}
    for r in results:
        if not r.success and r.error_type:
            error_types[r.error_type] = error_types.get(r.error_type, 0) + 1
    if error_types:
        print(f"    失敗内訳: {error_types}")
    return pct, infra_pct


def main() -> int:
    user = os.environ.get("WEBSHARE_USERNAME", "")
    pw = os.environ.get("WEBSHARE_PASSWORD", "")
    if not user or not pw:
        print("❌ WEBSHARE_USERNAME / WEBSHARE_PASSWORD が未設定")
        return 1

    secrets = [user, pw]

    print(f"WebShare username: {_mask(user)}")
    print(f"WebShare password: {_mask(pw)}")
    print(f"テスト動画数: {len(TEST_VIDEOS)}")

    proxy_config = WebshareProxyConfig(proxy_username=user, proxy_password=pw)
    proxy_url = proxy_config.url

    ip_no_proxy = check_ip_no_proxy()
    ip_with_proxy = check_ip_with_proxy(proxy_url, secrets)

    _section("Proxy 疎通判定")
    if ip_no_proxy and ip_with_proxy:
        if ip_no_proxy != ip_with_proxy:
            print(f"  ✅ proxy 経由で IP が変わっている: {ip_no_proxy} → {ip_with_proxy}")
        else:
            print(f"  ⚠️ IP が同じ ({ip_no_proxy})。proxy が機能していない可能性")
    else:
        print("  ⚠️ どちらかの IP 取得に失敗。判定不能")

    api_no_proxy = YouTubeTranscriptApi()
    api_with_proxy = YouTubeTranscriptApi(proxy_config=proxy_config)

    _section("C-pre. transcript 在庫確認 (list, proxy なし)")
    print("  → 各動画に実際にどの言語の字幕が存在するか YouTube に問い合わせる")
    print("  → daily_news.py が要求する languages=['en','ja'] が在庫に含まれるかも確認")
    inventory_no_proxy: dict[str, Optional[list[tuple[str, bool]]]] = {}
    for video_id, label in TEST_VIDEOS:
        langs, err = list_inventory(api_no_proxy, video_id, label, secrets)
        inventory_no_proxy[video_id] = langs
        if langs is None:
            print(f"  • [{video_id}] ❌ list 失敗: {err}")
        else:
            has_en = any(lc == "en" for lc, _ in langs)
            has_ja = any(lc == "ja" for lc, _ in langs)
            marks = []
            if has_en:
                marks.append("en✓")
            if has_ja:
                marks.append("ja✓")
            mark_str = " ".join(marks) if marks else "en✗ ja✗"
            langs_str = ", ".join(
                f"{lc}{'(auto)' if gen else ''}" for lc, gen in langs
            )
            print(f"  • [{video_id}] {mark_str} | 全{len(langs)}言語: {langs_str}")

    _section("C. transcript 取得 (proxy なし)")
    results_no_proxy = run_batch(api_no_proxy, TEST_VIDEOS, secrets)

    _section("D-pre. transcript 在庫確認 (list, proxy あり)")
    inventory_with_proxy: dict[str, Optional[list[tuple[str, bool]]]] = {}
    for video_id, _label in TEST_VIDEOS:
        langs, err = list_inventory(api_with_proxy, video_id, _label, secrets)
        inventory_with_proxy[video_id] = langs
        if langs is None:
            print(f"  • [{video_id}] ❌ list 失敗: {err}")
        else:
            print(f"  • [{video_id}] ✅ list 成功 ({len(langs)} 言語)")

    _section("D. transcript 取得 (proxy あり)")
    results_with_proxy = run_batch(api_with_proxy, TEST_VIDEOS, secrets)

    _section("E. 言語フィルタ切り分け (proxy あり)")
    video_id, label = LANG_TEST_VIDEO
    lang_results: list[tuple[list[str], TranscriptResult]] = []
    for langs in LANG_PATTERNS:
        print(f"  • languages={langs}")
        r = fetch_one(api_with_proxy, video_id, label, langs, secrets)
        if r.success:
            print(f"    ✅ ok ({r.transcript_chars} chars)")
        else:
            print(f"    ❌ {r.error_type}: {r.error_msg}")
        lang_results.append((langs, r))

    _section("成功率サマリー")
    pn_pct, pn_infra_pct = summarize(results_no_proxy, "proxy なし")
    pa_pct, pa_infra_pct = summarize(results_with_proxy, "proxy あり")
    print()
    print("  言語別 (proxy あり, 1 video):")
    for langs, r in lang_results:
        status = "✅" if r.success else f"❌ {r.error_type}"
        print(f"    {langs}: {status}")

    _section("結論判定 (Issue #18 の判定表)")
    print("  ※ 判定はインフラ成功率（動画側起因の失敗を除外した値）で行う")
    print(f"  proxy なし: 全体 {pn_pct:.0f}% / インフラ {pn_infra_pct:.0f}%")
    print(f"  proxy あり: 全体 {pa_pct:.0f}% / インフラ {pa_infra_pct:.0f}%")
    print()

    if pa_infra_pct >= 80:
        verdict = "✅ proxy 経由で 80%+ 成功 → Issue #17 をそのまま着手可"
    elif pa_infra_pct < 50 and pn_infra_pct < 50:
        verdict = "❌ 全パターン低成功率 → youtube-transcript-api / yt-dlp 移行検討"
    elif pa_infra_pct < 50:
        verdict = (
            "⚠️ proxy 経由でも 50% 未満 → "
            "WebShare プランを Residential に変更が必須。Issue #17 はその後"
        )
    elif pn_infra_pct > pa_infra_pct:
        verdict = (
            "⚠️ proxy なしの方が成功率高い → "
            "proxy 設定がむしろ邪魔。WebShare 設定を見直し"
        )
    else:
        verdict = (
            f"△ proxy あり {pa_infra_pct:.0f}% — Residential 化で改善余地あり。"
            "Issue #17 と並行検討"
        )
    print(f"  {verdict}")

    print()
    print("📋 newspaper-decisions に転記する値:")
    print(f"  - egress IP (proxy なし): {ip_no_proxy}")
    print(f"  - egress IP (proxy あり): {ip_with_proxy}")
    print(f"  - 成功率 proxy なし: 全体 {pn_pct:.1f}% / インフラ {pn_infra_pct:.1f}%")
    print(f"  - 成功率 proxy あり: 全体 {pa_pct:.1f}% / インフラ {pa_infra_pct:.1f}%")
    err_types_pa: dict[str, int] = {}
    for r in results_with_proxy:
        if not r.success and r.error_type:
            err_types_pa[r.error_type] = err_types_pa.get(r.error_type, 0) + 1
    print(f"  - proxy あり失敗内訳: {err_types_pa}")
    no_lang_videos = [
        vid
        for vid, langs in inventory_no_proxy.items()
        if langs is not None
        and not any(lc in ("en", "ja") for lc, _ in langs)
    ]
    if no_lang_videos:
        print(
            f"  - en/ja 字幕が在庫に無い動画: {len(no_lang_videos)} 本 "
            f"({no_lang_videos}) → languages フィルタ拡張の検討材料"
        )
    print(f"  - 結論: {verdict}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
