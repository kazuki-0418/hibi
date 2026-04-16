# Daily News Task

Working directory: /Users/kazukijo/Desktop/dev/Personal-Daily-News

## Step 1: 記事を取得

```bash
cd /Users/kazukijo/Desktop/dev/Personal-Daily-News && source .venv/bin/activate && python fetch_articles.py
```

## Step 2: 記事をエンリッチして enriched_articles.json に保存

`articles.json` を読み込み、各記事について以下の4フィールドを日本語で生成してください。

あなたはKazukiのパーソナルリサーチアナリストです。
Kazukiの現在のコンテキスト：
- バンクーバー在住の日本人エンジニア
- Monogatari（留学生・ワーホリ向け日本語マーケットプレイス）を開発中
- カナダでFrontend × AIポジションの就職活動中
- フリーランスのクライアント獲得・信頼構築にも関心あり

各記事に対して以下を生成：
- **summary**: 1〜2文の概要
- **learning**: 学べる技術的概念・知見
- **practical_application**: Kazukiの状況への応用（以下の観点から該当するものを1〜3文）
  - Monogatariや個人プロジェクトへの技術的応用
  - 就職活動のポートフォリオ・面接トークポイント
  - クライアントや同僚との信頼構築に役立つ知識
- **category**: `AI/LLM` / `Frontend` / `Startup` / `Career` / `Tech News` のいずれか
- **importance**: 1〜3の整数（3 = Kazukiの優先事項に最も関連）

以下の形式で `/Users/kazukijo/Desktop/dev/Personal-Daily-News/enriched_articles.json` に保存してください：

```json
[
  {
    "title": "記事タイトル",
    "url": "https://...",
    "source": "HackerNews",
    "summary": "概要文",
    "learning": "学べること",
    "practical_application": "実践的な応用",
    "category": "AI/LLM",
    "importance": 3
  },
  ...
]
```

全ソース（HackerNews, Reddit, ITmedia, Product Hunt）の記事をすべて含めてください。

## Step 3: HTMLメールを送信

```bash
cd /Users/kazukijo/Desktop/dev/Personal-Daily-News && source .venv/bin/activate && python send_mail.py
```

送信完了したら「✅ Daily News sent: YYYY-MM-DD」と出力してください。
