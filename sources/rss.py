import feedparser


def fetch(feed_url: str, top_n: int, source_name: str) -> list[dict]:
    feed = feedparser.parse(feed_url)
    articles = []
    for entry in feed.entries[:top_n]:
        articles.append({
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "summary": entry.get("summary", ""),
            "source": source_name,
        })
    return articles
