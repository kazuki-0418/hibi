"""channels.yaml の channel_id を YouTube Data API で検証する。

使い方:
    python scripts/verify_channels.py channels.yaml

出力:
    ✅ UCxxx - NetworkChuck (subscribers: 3.8M)
    ❌ UCmatthew_berman - Matthew Berman (NOT FOUND)
    ⚠️  UC... - Marc Lou (expected: Marc Lou, actual: Some Other Channel)
"""

import os
import sys
import yaml
import requests
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]


def verify_channels(yaml_path: str):
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    channels = data["channels"]
    # API は1回で最大50個の channel_id を検証できる
    ids = [c["channel_id"] for c in channels if c["channel_id"] != "要確認"]

    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={
            "part": "snippet,statistics",
            "id": ",".join(ids),
            "key": YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    result = resp.json()

    found_ids = {item["id"]: item for item in result.get("items", [])}

    for ch in channels:
        name = ch["name"]
        cid = ch["channel_id"]

        if cid == "要確認":
            print(f"⚠️  {name} - channel_id is '要確認' (needs manual lookup)")
            continue

        if cid not in found_ids:
            print(f"❌ {cid} - {name} (NOT FOUND on YouTube)")
            continue

        actual = found_ids[cid]
        actual_name = actual["snippet"]["title"]
        subs = int(actual["statistics"].get("subscriberCount", 0))

        if actual_name.lower() != name.lower():
            print(f"⚠️  {cid} - expected: {name}, actual: {actual_name}")
        else:
            print(f"✅ {cid} - {name} (subs: {subs:,})")


if __name__ == "__main__":
    verify_channels(sys.argv[1])
