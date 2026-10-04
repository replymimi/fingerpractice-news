"""Fetch whole-market daily quotes for every TWSE (上市) and TPEx (上櫃) stock,
plus 投信 net buy/sell, and keep a rolling window of trading days on disk.

One file per trading day: data/stocks/daily/YYYY-MM-DD.json
    {"date": "...", "trust_ok": true,
     "stocks": {"2330": [open, high, low, close, change, volume_lots, trust_net_lots]}}
Names live in data/stocks/names.json ({"2330": ["台積電", "上市"]}) instead of
being repeated in every daily file.

  - change is the exchange's own 漲跌價差 (vs. the reference price, so ex-dividend
    days are handled correctly); null when the exchange doesn't give a number.
  - volume and trust_net are in 張 (1 張 = 1000 股). trust_net is null when the
    institutional table couldn't be fetched (the day is re-fetched next run).

Usage:
    python scripts/fetch_stock_history.py              # daily: fill the latest missing days
    python scripts/fetch_stock_history.py --backfill 150
"""
import argparse
import glob
import json
import os
import sys
import time
from datetime import timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, log, load_json, save_json, now_taipei

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DAILY_DIR = os.path.join(DATA_DIR, "stocks", "daily")
NAMES_PATH = os.path.join(DATA_DIR, "stocks", "names.json")
KEEP_DAYS = 150  # trading days kept on disk: enough for 20-week MA, 60MA slope, 120-day high
TWSE_PAUSE = 3   # TWSE blocks clients that hit it faster than ~1 req / 2-3 s


def num(s):
    try:
        return float(str(s).replace(",", "").replace("+", "").strip())
    except ValueError:
        return None


def get_json(url, params):
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------- TWSE 上市 ----------

def twse_quotes(d):
    j = get_json("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                 {"date": d.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"})
    if j.get("stat") != "OK":
        return {}  # holiday / not published yet
    for t in j.get("tables", []):
        if "每日收盤行情" in (t.get("title") or ""):
            out = {}
            for row in t["data"]:
                o, h, l, c = (num(x) for x in row[5:9])
                if None in (o, h, l, c):
                    continue  # no trades that day
                sign = row[9]
                chg = num(row[10])
                if chg is not None:
                    if "-" in sign:
                        chg = -chg
                    elif "+" not in sign and chg != 0:
                        chg = None  # e.g. "X" on ex-rights days: no usable change
                out[row[0].strip()] = [row[1].strip(), "上市", o, h, l, c, chg, round(num(row[2]) / 1000)]
            return out
    raise RuntimeError("TWSE: 每日收盤行情 table missing")


def twse_trust(d):
    j = get_json("https://www.twse.com.tw/rwd/zh/fund/T86",
                 {"date": d.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"})
    if j.get("stat") != "OK":
        return None
    assert j["fields"][10].startswith("投信買賣超"), j["fields"][10]
    return {row[0].strip(): round(num(row[10]) / 1000) for row in j["data"]}


# ---------- TPEx 上櫃 ----------

def tpex_date(d):
    return d.strftime("%Y/%m/%d")


def tpex_quotes(d):
    j = get_json("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc",
                 {"date": tpex_date(d), "type": "EW", "response": "json"})
    out = {}
    for row in j["tables"][0]["data"]:
        c, chg, o, h, l = num(row[2]), num(row[3]), num(row[4]), num(row[5]), num(row[6])
        if None in (o, h, l, c):
            continue
        out[row[0].strip()] = [row[1].strip(), "上櫃", o, h, l, c, chg, round(num(row[7]) / 1000)]
    return out


def tpex_trust(d):
    j = get_json("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
                 {"type": "Daily", "sect": "EW", "date": tpex_date(d), "response": "json"})
    t = j["tables"][0]
    if not t["data"]:
        return None
    # columns: 外資(不含自營) x3, 外資自營 x3, 外資合計 x3, 投信 買/賣/超 = index 11-13
    return {row[0].strip(): round(num(row[13]) / 1000) for row in t["data"]}


# ---------- one day ----------

def fetch_day(d):
    """Returns the day dict, None for a market holiday. Raises if only part of
    the market came back, so a half-filled day is never written."""
    listed = twse_quotes(d)
    time.sleep(TWSE_PAUSE)
    otc = tpex_quotes(d)
    if not listed and not otc:
        return None
    if not listed or not otc:
        raise RuntimeError(f"only one market has data (上市 {len(listed)}, 上櫃 {len(otc)})")

    trust, trust_ok = {}, True
    for fn in (twse_trust, tpex_trust):
        try:
            part = fn(d)
            if part is None:
                trust_ok = False
            else:
                trust.update(part)
        except Exception as e:
            log(f"  WARN {fn.__name__} {d:%Y-%m-%d}: {e}")
            trust_ok = False
        time.sleep(TWSE_PAUSE)

    stocks, names = {}, {}
    for code, row in {**listed, **otc}.items():
        names[code] = row[:2]
        stocks[code] = row[2:] + [trust.get(code, 0 if trust_ok else None)]
    return {"date": d.strftime("%Y-%m-%d"), "trust_ok": trust_ok, "stocks": stocks, "names": names}


def day_path(d):
    return os.path.join(DAILY_DIR, f"{d:%Y-%m-%d}.json")


def needs_fetch(d):
    existing = load_json(day_path(d))
    return existing is None or not existing.get("trust_ok", False)


def save_day(day):
    # the newest day on disk decides names (renamed stocks); older days only add missing codes
    day_names = day.pop("names")
    existing = sorted(glob.glob(os.path.join(DAILY_DIR, "*.json")))
    is_newest = not existing or day["date"] >= os.path.basename(existing[-1])[:10]
    names = load_json(NAMES_PATH, {})
    names = {**names, **day_names} if is_newest else {**day_names, **names}
    save_json(NAMES_PATH, names)

    path = os.path.join(DAILY_DIR, f"{day['date']}.json")
    os.makedirs(DAILY_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False, separators=(",", ":"))


def prune():
    files = sorted(glob.glob(os.path.join(DAILY_DIR, "*.json")))
    for f in files[:-KEEP_DAYS]:
        os.remove(f)
    return min(len(files), KEEP_DAYS)


def run(target_trading_days, max_calendar_days):
    """Walk back from today, fetching weekdays that are missing, until we have
    seen target_trading_days trading days or run out of calendar days."""
    today = now_taipei().date()
    seen = 0
    for n in range(max_calendar_days):
        d = today - timedelta(days=n)
        if d.weekday() >= 5:
            continue
        if not needs_fetch(d):
            seen += 1
        else:
            try:
                day = fetch_day(d)
            except Exception as e:
                log(f"  ERROR {d}: {e}")
                continue
            if day is None:
                continue  # holiday, or today's data not published yet
            save_day(day)
            seen += 1
            log(f"  {d}: {len(day['stocks'])} stocks{'' if day['trust_ok'] else ' (投信 missing, will retry)'}")
        if seen >= target_trading_days:
            break


SHARES_PATH = os.path.join(DATA_DIR, "stocks", "shares.json")


def fetch_shares():
    """Issued common shares per stock, for 週轉率. Latest snapshot only (it
    changes rarely); on failure the previous file is kept."""
    shares = load_json(SHARES_PATH, {})
    try:
        rows = get_json("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", {})
        for x in rows:
            n = num(x.get("已發行普通股數或TDR原股發行股數"))
            if n:
                shares[x["公司代號"].strip()] = int(n)
    except Exception as e:
        log(f"  WARN TWSE shares: {e}")
    try:
        # the OTC daily quote table carries 發行股數 (column 14); walk back to the last trading day
        today = now_taipei().date()
        for n_back in range(10):
            d = today - timedelta(days=n_back)
            if d.weekday() >= 5:
                continue
            data = get_json("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc",
                            {"date": tpex_date(d), "type": "EW", "response": "json"})["tables"][0]["data"]
            if data:
                for row in data:
                    n = num(row[14])
                    if n:
                        shares[row[0].strip()] = int(n)
                break
    except Exception as e:
        log(f"  WARN TPEx shares: {e}")
    save_json(SHARES_PATH, shares)
    return len(shares)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="make sure the last N trading days exist")
    args = ap.parse_args()
    if args.backfill:
        run(args.backfill, args.backfill * 2 + 30)
    else:
        run(5, 10)  # daily: covers a missed run or two, and retries days with missing 投信
    log(f"stock history: {prune()} trading days on disk")
    log(f"issued shares: {fetch_shares()} stocks")


if __name__ == "__main__":
    main()
