import requests

HN_BASE = "https://hacker-news.firebaseio.com/v0"


def fetch(top_n: int = 10) -> list[dict]:
    resp = requests.get(f"{HN_BASE}/topstories.json", timeout=10)
    resp.raise_for_status()
    story_ids = resp.json()[:top_n]

    articles = []
    for story_id in story_ids:
        try:
            item_resp = requests.get(f"{HN_BASE}/item/{story_id}.json", timeout=10)
            item_resp.raise_for_status()
            item = item_resp.json()
            if not item or item.get("type") != "story":
                continue
            articles.append({
                "title": item.get("title", ""),
                "url": item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                "score": item.get("score", 0),
                "author": item.get("by", ""),
                "source": "HackerNews",
            })
        except Exception:
            continue

    return articles
