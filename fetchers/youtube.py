"""YouTube fetcher — uploads playlist metadata only (no transcript)."""

from datetime import datetime, timezone


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
        published_raw = entry["contentDetails"].get("videoPublishedAt")
        if published_raw:
            published_at = published_raw
        else:
            published_at = datetime.now(timezone.utc).isoformat()

        items.append(
            {
                "source_type": "youtube",
                "source_name": source["name"],
                "category": source.get("category"),
                "content_id": video_id,
                "title": entry["snippet"]["title"],
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": published_at,
                "description": entry["snippet"].get("description", ""),
            }
        )
    return items
