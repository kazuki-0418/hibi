"""
Fetch articles from all sources and save to articles.json.
Used by the Claude Code scheduled task.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml
from dotenv import load_dotenv

from sources import hackernews, reddit, rss

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def fetch_all(cfg: dict) -> dict[str, list[dict]]:
    results = {}

    def _hn():
        log.info("Fetching HackerNews...")
        return "HackerNews", hackernews.fetch(top_n=cfg["sources"]["hackernews"]["top_n"])

    def _reddit():
        log.info("Fetching Reddit...")
        r_cfg = cfg["sources"]["reddit"]
        return "Reddit", reddit.fetch(subreddits=r_cfg["subreddits"], top_n=r_cfg["top_n"])

    def _itmedia():
        log.info("Fetching ITmedia...")
        itm = cfg["sources"]["itmedia"]
        return "ITmedia", rss.fetch(feed_url=itm["feed_url"], top_n=itm["top_n"], source_name="ITmedia")

    def _producthunt():
        log.info("Fetching Product Hunt...")
        ph = cfg["sources"]["product_hunt"]
        return "ProductHunt", rss.fetch(feed_url=ph["feed_url"], top_n=ph["top_n"], source_name="Product Hunt")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fn) for fn in (_hn, _reddit, _itmedia, _producthunt)]
        for future in as_completed(futures):
            try:
                name, articles = future.result()
                results[name] = articles
                log.info("Fetched %d articles from %s", len(articles), name)
            except Exception as e:
                log.error("Fetch failed: %s", e)

    return results


def main():
    cfg = load_config()
    articles_by_source = fetch_all(cfg)

    output_path = "articles.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(articles_by_source, f, ensure_ascii=False, indent=2)

    log.info("Saved to %s", output_path)

    # Print summary for Claude Code agent to read
    for source, articles in articles_by_source.items():
        print(f"\n=== {source} ({len(articles)} articles) ===")
        for a in articles:
            print(f"  - {a['title']}")
            print(f"    {a['url']}")


if __name__ == "__main__":
    main()
