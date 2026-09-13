"""Fetch index levels (DJIA, S&P 500, NASDAQ, SOX, TAIEX) via Yahoo Finance's
public chart endpoint (no key required).

Writes data/raw/market.json:
{ "us": [ {name, symbol, price, prev_close, chg, chg_pct}, ... ], "tw": [ ... ] }
"""
import os
import sys
import yaml
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, RAW_DIR, log, save_json, fetch_with_cache_fallback

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def fetch_symbol(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    meta = r.json()["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    prev = meta["previousClose"]
    return {
        "price": price,
        "prev_close": prev,
        "chg": round(price - prev, 2),
        "chg_pct": round((price - prev) / prev * 100, 2),
    }


def main():
    with open(os.path.join(ROOT, "sources.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    output = {}
    for region in ("us", "tw"):
        rows = []
        for entry in cfg["market_indices"][region]:
            def _fetch(entry=entry):
                data = fetch_symbol(entry["symbol"])
                return {"name": entry["name"], "symbol": entry["symbol"], **data}

            row, used_cache = fetch_with_cache_fallback(
                _fetch, f"market_{entry['symbol'].strip('^')}.json", label=entry["name"]
            )
            if row:
                rows.append(row)
                log(f"  {entry['name']}: {row['price']} ({row['chg_pct']:+.2f}%){' [cache]' if used_cache else ''}")
        output[region] = rows

    save_json(os.path.join(RAW_DIR, "market.json"), output)
    log("market.json written")


if __name__ == "__main__":
    main()
