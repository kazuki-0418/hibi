"""YouTube fetcher — uploads playlist metadata + transcript via WebShare proxy."""

from youtube_transcript_api import YouTubeTranscriptApi


def fetch_recent_items(
    youtube_client, source: dict, max_results: int
) -> list[dict]:
    """Return the latest uploads for a YouTube source. 2 units/channel."""
    channel_id = source["channel_id"]
    ch = (
        youtube_client.channels()
        .list(part="contentDetails", id=channel_id)
        .execute()
    )
    if not ch.get("items"):
        print(f"  ⚠️  Channel not found: {channel_id}")
        return []

    uploads_playlist = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = (
        youtube_client.playlistItems()
        .list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist,
            maxResults=max_results,
        )
        .execute()
    )

    items = []
    for entry in pl.get("items", []):
        video_id = entry["contentDetails"]["videoId"]
        items.append(
            {
                "source_type": "youtube",
                "source_name": source["name"],
                "category": source.get("category"),
                "content_id": video_id,
                "title": entry["snippet"]["title"],
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": entry["contentDetails"]["videoPublishedAt"],
                "description": entry["snippet"].get("description", ""),
            }
        )
    return items


def get_content_text(
    ytt_api: YouTubeTranscriptApi, item: dict
) -> str | None:
    """Return transcript text, or ``None`` if unavailable."""
    try:
        fetched = ytt_api.fetch(item["content_id"], languages=["en", "ja"])
        return " ".join(snippet.text for snippet in fetched.snippets)
    except Exception as e:
        print(f"    [skip] transcript unavailable: {type(e).__name__}: {e}")
        return None
