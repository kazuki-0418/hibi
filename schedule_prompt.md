# Daily News Task

Working directory: /Users/kazukijo/Desktop/dev/Personal-Daily-News

## Steps

1. Activate venv and fetch articles:
```
source .venv/bin/activate && python fetch_articles.py
```

2. Read `articles.json` and summarize each source in Japanese (3-5 bullet points per source, include URLs).

3. Save summaries to `summaries.json` in this format:
```json
{
  "HackerNews": "- **タイトル**\n  ...",
  "Reddit": "...",
  "ITmedia": "...",
  "ProductHunt": "..."
}
```

4. Send email:
```
source .venv/bin/activate && python send_mail.py --subject "Daily Tech News - $(date +%Y-%m-%d)" --from-json summaries.json
```
