# セットアップガイド

## 必要なもの

- Python 3.11+
- Gmail アカウント（アプリパスワード）
- Claude Code Max プラン

## 手順

### 1. 依存パッケージのインストール

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集：

```env
GMAIL_ADDRESS=your_gmail@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

> **Gmail アプリパスワードの発行手順**
> 1. Google アカウント → セキュリティ
> 2. 2段階認証を有効化
> 3. アプリパスワードを生成（16文字）

### 3. スケジュールタスクの初回実行

Claude Code サイドバーの「Scheduled」から `daily-news` を選び、**「Run now」** をクリック。
ツール許可の確認が出るので承認すると、以降は毎朝 6:10 に自動実行される。

### 4. 手動実行

```bash
source .venv/bin/activate

# 記事取得
python fetch_articles.py

# メール送信（enriched_articles.json が必要）
python send_mail.py
```

## ファイル構成

```
Personal-Daily-News/
├── fetch_articles.py        # 記事取得 → articles.json
├── send_mail.py             # enriched_articles.json → Gmail 送信
├── mailer.py                # HTML メール構築
├── sources/
│   ├── hackernews.py        # HN Firebase API
│   ├── reddit.py            # Reddit JSON API
│   └── rss.py               # feedparser 汎用（ITmedia / Product Hunt）
├── templates/
│   └── email.html           # メール HTML テンプレート
├── config.yaml              # ソース設定
├── .env                     # 認証情報（git 管理外）
├── .env.example             # テンプレート
├── requirements.txt
└── schedule_prompt.md       # Claude Code スケジュールタスク用プロンプト
```
