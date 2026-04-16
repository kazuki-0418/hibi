import requests

HEADERS = {"User-Agent": "PersonalDailyNews/1.0 (personal use)"}


def fetch(subreddits: list[str], top_n: int = 5) -> list[dict]:
    articles = []
    for subreddit in subreddits:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={top_n}"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            posts = resp.json()["data"]["children"]
            for post in posts[:top_n]:
                data = post["data"]
                articles.append({
                    "title": data.get("title", ""),
                    "url": data.get("url", f"https://www.reddit.com{data.get('permalink', '')}"),
                    "score": data.get("score", 0),
                    "subreddit": subreddit,
                    "source": "Reddit",
                })
        except Exception:
            continue

    return articles
