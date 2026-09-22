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
import re
import sys
import yaml
import feedparser
import requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, RAW_DIR, log, save_json, fetch_with_cache_fallback

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
ITEMS_PER_SOURCE = 4
CANDIDATES_TO_SCAN = 60  # how many raw entries to look through when a source needs keyword filtering


def parse_entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    return None


def matches_topic(entry, keywords):
    """Whole-word match against the TITLE only. Matching the body text lets
    generic fragments like 'rate' hit incidentally in any long article
    (e.g. inside 'operate', or a passing 'job market' mention in an
    unrelated story), and plain substring matching hits inside unrelated
    words too — word-boundary regex on the title alone is the only
    combination that actually tracked the real topic in testing."""
    if not keywords:
        return True
    title = entry.get("title", "")
    return any(re.search(r"\b" + re.escape(kw) + r"\b", title, re.IGNORECASE) for kw in keywords)


def fetch_one_source(src):
    keywords = src.get("topic_keywords")

    def _fetch():
        r = requests.get(src["feed_url"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        if not d.entries:
            raise ValueError("0 entries parsed")
        scan_limit = CANDIDATES_TO_SCAN if keywords else ITEMS_PER_SOURCE
        items = []
        for entry in d.entries[:scan_limit]:
            if not matches_topic(entry, keywords):
                continue
            items.append({
                "source": src["name"],
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "published_iso": parse_entry_time(entry),
                "summary_raw": (entry.get("summary", "") or "")[:600],
            })
            if len(items) >= ITEMS_PER_SOURCE:
                break
        if keywords and not items:
            raise ValueError(f"0 of {scan_limit} entries matched topic_keywords")
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
