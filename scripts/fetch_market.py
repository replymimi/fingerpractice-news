"""Fetch index levels. Yahoo Finance's public chart endpoint covers most
symbols; the OTC index (櫃買) is no longer served by Yahoo (404 'delisted'),
so it comes from the TPEx official OpenAPI instead.

Every row carries `as_of` (when the quote is actually from). A row served
from the cache fallback is dropped if it is older than STALE_CACHE_DAYS —
showing a number is worse than showing nothing when the person reading it
trades on it (a dead symbol sat on a frozen cached value for ~3 weeks).

Writes data/raw/market.json:
{ "us": [ {name, symbol, price, prev_close, chg, chg_pct, as_of, is_currency}, ... ], "tw": [ ... ] }
"""
import os
import sys
import yaml
import requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, RAW_DIR, TAIPEI, log, save_json, fetch_with_cache_fallback

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
STALE_CACHE_DAYS = 4


def fetch_yahoo(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    meta = r.json()["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    prev = meta["previousClose"]
    as_of = datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc).astimezone(TAIPEI)
    return {
        "price": price,
        "prev_close": prev,
        "chg": round(price - prev, 2),
        "chg_pct": round((price - prev) / prev * 100, 2),
        "as_of": as_of.isoformat(),
    }


def fetch_tpex():
    """TPEx OpenAPI /tpex_index returns the latest two trading days, oldest first."""
    r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_index", headers=HEADERS, timeout=20)
    r.raise_for_status()
    rows = r.json()
    if len(rows) < 2:
        raise ValueError(f"tpex_index returned {len(rows)} rows, need 2")
    prev_row, last_row = rows[-2], rows[-1]
    price, prev = float(last_row["Close"]), float(prev_row["Close"])
    reported_change = float(last_row["Change"])
    if abs((price - prev) - reported_change) > 0.02:
        raise ValueError(f"TPEx change mismatch: close diff {price - prev:.2f} vs reported {reported_change}")
    d = last_row["Date"]  # e.g. "20261002"
    as_of = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), 13, 30, tzinfo=TAIPEI)  # TPEx closes 13:30
    return {
        "price": price,
        "prev_close": prev,
        "chg": round(price - prev, 2),
        "chg_pct": round((price - prev) / prev * 100, 2),
        "as_of": as_of.isoformat(),
    }


def is_stale_cache(row):
    as_of = row.get("as_of")
    if not as_of:
        return True  # legacy cache entry with no date — can't vouch for it
    age = datetime.now(timezone.utc) - datetime.fromisoformat(as_of)
    return age.days > STALE_CACHE_DAYS


def main():
    with open(os.path.join(ROOT, "sources.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    output = {}
    for region in ("us", "tw"):
        rows = []
        for entry in cfg["market_indices"][region]:
            def _fetch(entry=entry):
                if entry.get("provider") == "tpex":
                    data = fetch_tpex()
                else:
                    data = fetch_yahoo(entry["symbol"])
                return {
                    "name": entry["name"],
                    "symbol": entry.get("symbol") or entry["id"],
                    "is_currency": bool(entry.get("is_currency")),
                    **data,
                }

            key = (entry.get("symbol") or entry["id"]).strip("^")
            row, used_cache = fetch_with_cache_fallback(_fetch, f"market_{key}.json", label=entry["name"])
            if row and used_cache and is_stale_cache(row):
                log(f"  WARN {entry['name']}: live fetch failed and cached quote is older than "
                    f"{STALE_CACHE_DAYS} days (as_of={row.get('as_of')}) — NOT showing it")
                continue
            if row:
                rows.append(row)
                log(f"  {entry['name']}: {row['price']} ({row['chg_pct']:+.2f}%) as_of={row['as_of'][:16]}"
                    f"{' [cache]' if used_cache else ''}")
        output[region] = rows

    save_json(os.path.join(RAW_DIR, "market.json"), output)
    log("market.json written")


if __name__ == "__main__":
    main()
