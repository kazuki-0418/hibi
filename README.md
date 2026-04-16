# Personal AI Newspaper

毎朝 YouTube の技術チャンネルから最新動画を取得し、Claude が日本語で要約して Gmail に配信するパーソナルニュースレター。

## フロー

```
GitHub Actions（毎朝 UTC 13:00 = Vancouver 6:00 AM PDT）
  └─ daily_news.py
       ├─ YouTube Data API v3（playlistItems.list）
       │    └─ 対象3チャンネル × 最新3本 = 最大9動画
       ├─ youtube-transcript-api（字幕取得・無料）
       ├─ Claude Sonnet 4.6（日本語3行要約）
       └─ Gmail API（OAuth2）→ 受信トレイへ配信
```

## 対象チャンネル

| チャンネル | ID |
|---|---|
| Theo - t3.gg | UCbRP3c757lWg9M-U7TyEkXA |
| AI Explained | UCNJ1Ymd5yFuUPtn21xtRbbw |
| Fireship | UCsBjURrPoezykLs9EqgamOA |

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

## コスト

| サービス | コスト |
|---|---|
| Claude Sonnet 4.6 | 約 $0.05 / 日（9動画 × 15,000 chars） |
| YouTube Data API v3 | 無料枠内（約 60 units / 日、上限 10,000） |
| Gmail API | 無料 |
