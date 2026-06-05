# Personal AI Newspaper

毎朝 RSS フィードから最新記事を取得し、Claude が日本語で要約して Gmail に配信するパーソナルニュースレター。

## フロー

```
GitHub Actions（毎朝 UTC 13:17 = Vancouver 6:17 AM PDT）
  └─ daily_news.py
       ├─ sources.yaml で定義した RSS ソースからメタデータを取得（feedparser）
       ├─ 候補をランキング → digest plan → 試行プール化
       ├─ 本文取得（trafilatura + robots.txt 尊重）→ Claude 要約
       ├─ 本文不足時は link-only（要約なし）
       └─ Gmail API（OAuth2）→ 受信トレイへ配信（目標 5 本）
```

## ソース設定

`sources.yaml` で `type: rss` ソースを追加・削除できます。新規 feed は `scripts/verify_feeds.py` で検証してください。

## セットアップ

### 1. 依存パッケージのインストール

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

以下を `.env`（ローカル実行時）または GitHub Secrets（Actions 実行時）に設定：

| 変数名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API キー |
| `GMAIL_CLIENT_ID` | Google OAuth2 クライアント ID |
| `GMAIL_CLIENT_SECRET` | Google OAuth2 クライアントシークレット |
| `GMAIL_REFRESH_TOKEN` | Gmail 送信用 refresh token |
| `RECIPIENT_EMAIL` | 配信先メールアドレス |
| `DATABASE_URL` | Neon PostgreSQL の pooled connection string |
| `OPENAI_API_KEY` | Goal / subject embedding ranking（任意だが本番推奨） |
| `OBSIDIAN_VAULT_PAT` | **Actions のみ** — private vault `Obsidan-workspace` の read-only PAT（[docs/obsidian-vault-ci.md](docs/obsidian-vault-ci.md)） |

> **Gmail OAuth2 の取得:** Google Cloud Console で Gmail API を有効化し、OAuth2 認証フローで refresh_token を取得。

### 3. ローカル実行

```bash
source .venv/bin/activate
python daily_news.py
```

### 4. GitHub Actions による自動化

1. リポジトリの **Settings → Secrets and variables → Actions** に上記変数を登録（`OBSIDIAN_VAULT_PAT` 含む）
2. `.github/workflows/daily-news.yml` が毎朝 UTC 13:17 に自動実行
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
| Claude Haiku 4.5 | 約 $0.02 / 日（5 本 × RSS 本文上限） |
| Gmail API | 無料 |

## Idea mining

5 AI workflow (Collector / Extractor / Spotter / Ideator / Critic) で共通利用する Vault profile ローダーは [`idea_mining/README.md`](idea_mining/README.md) を参照。

## 法的ポジショニング

[`docs/legal-posture.md`](docs/legal-posture.md) を参照。
