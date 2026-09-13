"""Fetch RSS news for the 股市/總經 and 加密貨幣 columns.

Writes data/raw/news.json:
{
  "stocks": [ {source, title, link, published_iso, summary}, ... up to N per source ],
  "crypto": [ ... ]
}
Each source is fetched independently; if one feed fails, we fall back to its
own last-known-good cache instead of dropping the whole column.
"""
import os
import sys
import yaml
import feedparser
import requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, RAW_DIR, log, save_json, fetch_with_cache_fallback

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
ITEMS_PER_SOURCE = 4


def parse_entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return None


def fetch_one_source(src):
    def _fetch():
        r = requests.get(src["feed_url"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        if not d.entries:
            raise ValueError("0 entries parsed")
        items = []
        for entry in d.entries[:ITEMS_PER_SOURCE]:
            items.append({
                "source": src["name"],
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "published_iso": parse_entry_time(entry),
                "summary_raw": (entry.get("summary", "") or "")[:600],
            })
        return items

    items, used_cache = fetch_with_cache_fallback(_fetch, f"news_{src['id']}.json", label=src["name"])
    if used_cache:
        log(f"  -> {src['name']}: using cached copy")
    return items or []


def main():
    with open(os.path.join(ROOT, "sources.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    output = {}
    for column in ("stocks", "crypto"):
        log(f"Fetching news column: {column}")
        column_items = []
        for src in cfg["news"][column]:
            items = fetch_one_source(src)
            log(f"  {src['name']}: {len(items)} items")
            column_items.extend(items)
        output[column] = column_items

    save_json(os.path.join(RAW_DIR, "news.json"), output)
    log("news.json written")


if __name__ == "__main__":
    main()
