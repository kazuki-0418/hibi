# Personal Daily News

毎朝 4 つのニュースソースから記事を収集し、Claude が Kazuki 向けにエンリッチして Gmail に配信するパーソナルニュースレターシステム。

## フロー

```
Claude Code スケジュールタスク（毎朝 6:10）
  └─ fetch_articles.py    # 4ソースから記事取得 → articles.json
  └─ Claude がエンリッチ   # 要約・学び・応用・重要度を付与 → enriched_articles.json
  └─ send_mail.py         # HTML メール → Gmail
```

## ソース

| ソース | 方式 | 件数 |
|---|---|---|
| Hacker News | Firebase API | Top 10 |
| Reddit | JSON API | 各 5 件（LocalLLaMA / nextjs / machinelearning） |
| ITmedia | RSS | 最新 10 件 |
| Product Hunt | RSS | 最新 5 件 |

## ドキュメント

- [セットアップ](docs/setup.md)
- [アーキテクチャ](docs/architecture.md)
