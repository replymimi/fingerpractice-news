"""Check configured YouTube channels for new uploads and pull their English
transcript so the summarizer has real content to translate.

Needs env var YOUTUBE_API_KEY (free quota, see project README).

Run modes (--run-type):
  main         07:00 run — every channel EXCEPT those marked supplemental_run
  supplemental 10:00 run — ONLY channels marked supplemental_run (e.g. 游庭皓,
               whose livestream ends at 09:30 and isn't up yet at 07:00)

Writes/merges into data/raw/youtube.json:
{ "stocks": [ {source, title, video_url, published_iso, duration_note,
               transcript_raw}, ... ], "crypto": [ ... ] }
A supplemental run merges into the existing file rather than overwriting it,
so the 07:00 videos stay on the page.
"""
import argparse
import os
import sys
import yaml
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, RAW_DIR, log, load_json, save_json, fetch_with_cache_fallback

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_RECENT = 3            # how many latest uploads to check per channel
TRANSCRIPT_CHAR_LIMIT = 6000


def resolve_uploads_playlist(handle):
    r = requests.get(f"{API_BASE}/channels", params={
        "part": "contentDetails",
        "forHandle": handle.lstrip("@"),
        "key": API_KEY,
    }, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise ValueError(f"channel not found for handle {handle}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def recent_uploads(playlist_id):
    r = requests.get(f"{API_BASE}/playlistItems", params={
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": MAX_RECENT,
        "key": API_KEY,
    }, timeout=15)
    r.raise_for_status()
    videos = []
    for item in r.json().get("items", []):
        snip = item["snippet"]
        videos.append({
            "video_id": snip["resourceId"]["videoId"],
            "title": snip["title"],
            "published_iso": snip["publishedAt"],
        })
    return videos


def get_duration(video_id):
    import re as _re
    r = requests.get(f"{API_BASE}/videos", params={
        "part": "contentDetails", "id": video_id, "key": API_KEY,
    }, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return ""
    iso = items[0]["contentDetails"]["duration"]  # e.g. "PT14M20S"
    m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    h += 0
    total_min = h * 60 + mi
    return f"{total_min}:{s:02d}" if not h else f"{h}:{mi:02d}:{s:02d}"


def get_transcript_text(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        text = " ".join(seg["text"] for seg in transcript)
        return text[:TRANSCRIPT_CHAR_LIMIT]
    except Exception as e:
        log(f"    no transcript for {video_id}: {e}")
        return ""


def fetch_channel(src):
    def _fetch():
        playlist_id = resolve_uploads_playlist(src["handle"])
        videos = recent_uploads(playlist_id)
        # only keep the single most recent upload — the page shows "today's video", not a backlog
        if not videos:
            raise ValueError("no uploads returned")
        latest = videos[0]
        transcript = get_transcript_text(latest["video_id"])
        duration = get_duration(latest["video_id"])
        return [{
            "source": src["name"],
            "title": latest["title"],
            "video_url": f"https://www.youtube.com/watch?v={latest['video_id']}",
            "published_iso": latest["published_iso"],
            "duration": duration,
            "transcript_raw": transcript,
        }]

    items, used_cache = fetch_with_cache_fallback(_fetch, f"youtube_{src['id']}.json", label=src["name"])
    if used_cache:
        log(f"  -> {src['name']}: using cached copy")
    return items or []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-type", choices=["main", "supplemental"], default="main")
    args = parser.parse_args()

    if not API_KEY:
        log("ERROR: YOUTUBE_API_KEY not set — skipping YouTube fetch entirely")
        save_json(os.path.join(RAW_DIR, "youtube.json"), load_json(os.path.join(RAW_DIR, "youtube.json"), {"stocks": [], "crypto": []}))
        return

    with open(os.path.join(ROOT, "sources.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    existing = load_json(os.path.join(RAW_DIR, "youtube.json"), {"stocks": [], "crypto": []})
    output = {"stocks": [], "crypto": []} if args.run_type == "main" else existing

    for column in ("stocks", "crypto"):
        log(f"Fetching YouTube column: {column} ({args.run_type} run)")
        wanted = [
            s for s in cfg["youtube"][column]
            if bool(s.get("supplemental_run")) == (args.run_type == "supplemental")
        ]
        fresh_items = []
        for src in wanted:
            items = fetch_channel(src)
            log(f"  {src['name']}: {len(items)} item(s)")
            fresh_items.extend(items)

        if args.run_type == "supplemental":
            # replace any earlier entry from the same source, keep everything else
            names = {it["source"] for it in fresh_items}
            kept = [it for it in output.get(column, []) if it["source"] not in names]
            output[column] = kept + fresh_items
        else:
            output[column] = fresh_items

    save_json(os.path.join(RAW_DIR, "youtube.json"), output)
    log("youtube.json written")


if __name__ == "__main__":
    main()
