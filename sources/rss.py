from fetchers.rss import parse_feed


def fetch(feed_url: str, top_n: int, source_name: str) -> list[dict]:
    feed = parse_feed(feed_url)
    articles = []
    for entry in feed.entries[:top_n]:
        articles.append({
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "summary": entry.get("summary", ""),
            "source": source_name,
        })
    return articles
