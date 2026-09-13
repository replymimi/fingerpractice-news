"""Fetch sector fund-flow data from Tide (tide-tw.app) — a small independent
developer's public data files, not an official API. Falls back to the last
cached copy if the files move or the site is unreachable, so a change on
their end degrades gracefully instead of breaking the page.

Writes data/raw/tide.json: {"latest": ..., "daily_brief": ..., "daily_digest": ...}
"""
import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW_DIR, log, save_json, fetch_with_cache_fallback

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
BASE_URL = "https://tide-tw.app/data"
FILES = {
    "latest": "latest.json",
    "daily_brief": "daily_brief.json",
    "daily_digest": "daily_digest.json",
}


def main():
    output = {}
    for key, filename in FILES.items():
        def _fetch(filename=filename):
            r = requests.get(f"{BASE_URL}/{filename}", headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()

        data, used_cache = fetch_with_cache_fallback(_fetch, f"tide_{key}.json", label=f"Tide {key}")
        output[key] = data
        log(f"  {key}: {'ok' if data else 'unavailable'}{' [cache]' if used_cache else ''}")

    save_json(os.path.join(RAW_DIR, "tide.json"), output)
    log("tide.json written")


if __name__ == "__main__":
    main()
