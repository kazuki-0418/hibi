# Personal AI Newspaper

毎朝 YouTube の技術チャンネルと RSS フィードから最新コンテンツを取得し、Claude が日本語で要約して Gmail に配信するパーソナルニュースレター。

## フロー

```
GitHub Actions（毎朝 UTC 13:00 = Vancouver 6:00 AM PDT）
  └─ daily_news.py
       ├─ sources.yaml で定義した全ソースから並列にメタデータを取得
       │    ├─ YouTube: YouTube Data API v3 → playlistItems.list（2 units/channel）
       │    └─ RSS: feedparser
       ├─ 候補をシャッフル → 先頭 MAX_ATTEMPTS 本を試行プール化
       ├─ 本文取得・配信
       │    ├─ YouTube: メタデータのみ（新着動画はタイトル + リンク、要約なし）
       │    └─ RSS: trafilatura（本文抽出 + robots.txt 尊重）→ Claude 要約
       ├─ Claude Haiku 4.5（RSS 本文の日本語3行要約、要約不能時は空文字返却）
       └─ Gmail API（OAuth2）→ 受信トレイへ配信（目標 5 本）
```

## ソース設定

`sources.yaml` でソースを追加・削除できます。`type: youtube` と `type: rss` の 2 種類をサポート。

## セットアップ

### 1. 依存パッケージのインストール

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

以下の6つを `.env`（ローカル実行時）または GitHub Secrets（Actions 実行時）に設定：

| 変数名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API キー |
| `YOUTUBE_API_KEY` | YouTube Data API v3 キー |
| `GMAIL_CLIENT_ID` | Google OAuth2 クライアント ID |
| `GMAIL_CLIENT_SECRET` | Google OAuth2 クライアントシークレット |
| `GMAIL_REFRESH_TOKEN` | Gmail 送信用 refresh token |
| `RECIPIENT_EMAIL` | 配信先メールアドレス |
| `DATABASE_URL` | Neon PostgreSQL の pooled connection string |

> **Gmail OAuth2 の取得:** Google Cloud Console で Gmail API を有効化し、OAuth2 認証フローで refresh_token を取得。

### 3. ローカル実行

```bash
source .venv/bin/activate
python daily_news.py
```

### 4. GitHub Actions による自動化

1. リポジトリの **Settings → Secrets and variables → Actions** に上記6変数を登録
2. `.github/workflows/daily_news.yml` が毎朝 UTC 13:00 に自動実行
3. **Actions タブ → Daily News → Run workflow** で手動実行も可能

## Neon PostgreSQL セットアップ

記事の重複排除のため Neon を使用しています。

1. https://console.neon.tech でプロジェクト作成
2. リージョン: `AWS us-west-2 (Oregon)` 推奨
3. SQL Editor で `migrations/001_init.sql` を実行
4. **Pooled connection string** をコピー（`-pooler` が URL に含まれるもの）
5. `.env` に `DATABASE_URL` を追加
6. GitHub Secrets に `DATABASE_URL` を追加

### 接続テスト

```bash
python scripts/test_neon_connection.py
```

## コスト

| サービス | コスト |
|---|---|
| Claude Haiku 4.5 | 約 $0.02 / 日（9動画 × 15,000 chars。Sonnet 比 約 1/3）|
| YouTube Data API v3 | 無料枠内（約 60 units / 日、上限 10,000） |
| Gmail API | 無料 |

## Idea mining

5 AI workflow (Collector / Extractor / Spotter / Ideator / Critic) で共通利用する Vault profile ローダーは [`idea_mining/README.md`](idea_mining/README.md) を参照。

## 法的ポジショニング

Hibi は **kazuki 単独購読の private newspaper** として運用中。Perplexity 訴訟 (2025-08 提訴、東京地裁係属中) の含意で **商用化 / 第三者配信 / OSS 配布は保留**。判決後に再評価する。詳細と再開シグナルは [`docs/legal-posture.md`](docs/legal-posture.md) を参照。
