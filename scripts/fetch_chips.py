"""Fetch Taiwan stock chip data (籌碼面): institutional investor flows and
margin trading, for the whole market and for a small watchlist.

Two sources, split by what each one gives away for free:
  - TWSE open data (twse.com.tw): the full per-stock institutional buy/sell
    table, used for the market-wide top-N ranking. FinMind only offers this
    "all stocks for one day" query to paying sponsors.
  - FinMind (finmindtrade.com): market totals + per-stock data for the
    watchlist (price, institutional flows, margin, monthly revenue).
    Works without a token (300 req/hr); set FINMIND_TOKEN to raise it to 600.

Every part is fetched and cached independently, so one failing source only
degrades its own block of the page.

Writes data/raw/chips.json: {"market": {...}, "watchlist": [...]}
"""
import os
import sys
from datetime import timedelta

import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, RAW_DIR, log, save_json, now_taipei, fetch_with_cache_fallback

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_URL = "https://www.twse.com.tw/rwd/zh"
YI = 1e8  # 1 億


def to_num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def days_ago(n):
    return (now_taipei() - timedelta(days=n)).strftime("%Y-%m-%d")


# ---------- FinMind ----------

def finmind(dataset, **params):
    headers = dict(HEADERS)
    token = os.environ.get("FINMIND_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(FINMIND_URL, params={"dataset": dataset, **params}, headers=headers, timeout=30)
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset}: {j.get('msg')}")
    return j["data"]


def market_totals():
    """三大法人買賣超金額 + 融資融券餘額變化, whole market, latest trading day."""
    inst = finmind("TaiwanStockTotalInstitutionalInvestors", start_date=days_ago(14))
    margin = finmind("TaiwanStockTotalMarginPurchaseShortSale", start_date=days_ago(14))
    if not inst or not margin:
        return None

    date = max(r["date"] for r in inst)
    net = {r["name"]: (r["buy"] - r["sell"]) / YI for r in inst if r["date"] == date}
    m_date = max(r["date"] for r in margin)
    m = {r["name"]: r for r in margin if r["date"] == m_date}

    def chg(name):
        row = m.get(name)
        return row["TodayBalance"] - row["YesBalance"] if row else None

    margin_money_chg = chg("MarginPurchaseMoney")
    return {
        "date": date,
        "foreign": net.get("Foreign_Investor", 0) + net.get("Foreign_Dealer_Self", 0),
        "trust": net.get("Investment_Trust", 0),
        "dealer": net.get("Dealer_self", 0) + net.get("Dealer_Hedging", 0),
        "total": net.get("total", 0),
        "margin_date": m_date,
        "margin_money_chg": margin_money_chg / YI if margin_money_chg is not None else None,
        "short_chg": chg("ShortSale"),  # 張
    }


def stock_detail(stock):
    """One watchlist stock: price, institutional flows, margin, monthly revenue."""
    sid = stock["id"]
    price = finmind("TaiwanStockPrice", data_id=sid, start_date=days_ago(14))
    inst = finmind("TaiwanStockInstitutionalInvestorsBuySell", data_id=sid, start_date=days_ago(14))
    margin = finmind("TaiwanStockMarginPurchaseShortSale", data_id=sid, start_date=days_ago(14))
    revenue = finmind("TaiwanStockMonthRevenue", data_id=sid, start_date=days_ago(430))
    if not price:
        return None

    last = price[-1]
    prev_close = last["close"] - last["spread"]
    out = {
        "id": sid, "name": stock["name"], "date": last["date"],
        "close": last["close"], "chg": last["spread"],
        "chg_pct": last["spread"] / prev_close * 100 if prev_close else 0,
    }

    # institutional net, in 張 (1 張 = 1000 股)
    by_date = {}
    for r in inst:
        d = by_date.setdefault(r["date"], {"foreign": 0, "trust": 0, "dealer": 0})
        net = (r["buy"] - r["sell"]) / 1000
        if r["name"].startswith("Foreign"):
            d["foreign"] += net
        elif r["name"] == "Investment_Trust":
            d["trust"] += net
        elif r["name"].startswith("Dealer"):
            d["dealer"] += net
    dates = sorted(by_date)
    if dates:
        out["inst"] = {**by_date[dates[-1]], "date": dates[-1]}
        out["foreign_5d"] = sum(by_date[d]["foreign"] for d in dates[-5:])

    if margin:
        m = margin[-1]
        out["margin_chg"] = m["MarginPurchaseTodayBalance"] - m["MarginPurchaseYesterdayBalance"]
        out["margin_balance"] = m["MarginPurchaseTodayBalance"]
        out["short_chg"] = m["ShortSaleTodayBalance"] - m["ShortSaleYesterdayBalance"]

    if revenue:
        cur = revenue[-1]
        by_ym = {(r["revenue_year"], r["revenue_month"]): r["revenue"] for r in revenue}
        y, mo = cur["revenue_year"], cur["revenue_month"]
        last_year = by_ym.get((y - 1, mo))
        prev_month = by_ym.get((y, mo - 1) if mo > 1 else (y - 1, 12))
        out["revenue"] = {
            "label": f"{y} 年 {mo} 月",
            "amount_yi": cur["revenue"] / YI,
            "yoy": (cur["revenue"] / last_year - 1) * 100 if last_year else None,
            "mom": (cur["revenue"] / prev_month - 1) * 100 if prev_month else None,
        }
    return out


# ---------- TWSE ----------

def twse(path, date):
    r = requests.get(f"{TWSE_URL}/{path}", params={"date": date, "selectType": "ALLBUT0999",
                                                   "type": "ALLBUT0999", "response": "json"},
                     headers=HEADERS, timeout=30)
    j = r.json()
    return j if j.get("stat") == "OK" else None


def top_ranking(top_n):
    """外資／投信買賣超 TOP N (上市個股, ETF excluded), ranked by estimated
    amount = net shares x closing price, so cheap high-volume stocks don't
    crowd out the ones where real money moved."""
    # walk back to the latest day TWSE has published (weekends, holidays, typhoon days)
    for n in range(0, 10):
        date = (now_taipei() - timedelta(days=n)).strftime("%Y%m%d")
        t86 = twse("fund/T86", date)
        if t86 and t86.get("data"):
            break
    else:
        return None

    daily = twse("afterTrading/MI_INDEX", date)
    closes = {}
    for t in (daily or {}).get("tables", []):
        if "每日收盤行情" in (t.get("title") or ""):
            closes = {row[0].strip(): to_num(row[8]) for row in t["data"]}
    if not closes:
        raise RuntimeError(f"TWSE closing prices missing for {date}")

    rows = []
    for row in t86["data"]:
        code = row[0].strip()
        close = closes.get(code)
        if code.startswith("0") or not close:  # 0 開頭是 ETF / 受益憑證
            continue
        rows.append({
            "id": code, "name": row[1].strip(),
            "foreign": to_num(row[4]) * close / YI,
            "trust": to_num(row[10]) * close / YI,
        })

    def rank(key):
        ordered = sorted(rows, key=lambda r: r[key], reverse=True)
        pick = lambda lst: [{"id": r["id"], "name": r["name"], "amount": r[key]} for r in lst]
        return {
            "buy": pick([r for r in ordered[:top_n] if r[key] > 0]),
            "sell": pick([r for r in ordered[::-1][:top_n] if r[key] < 0]),
        }

    return {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "foreign": rank("foreign"), "trust": rank("trust")}


def main():
    with open(os.path.join(ROOT, "sources.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f).get("tw_chips", {})

    totals, used = fetch_with_cache_fallback(market_totals, "chips_totals.json", label="FinMind totals")
    log(f"  market totals: {'ok' if totals else 'unavailable'}{' [cache]' if used else ''}")

    ranking, used = fetch_with_cache_fallback(lambda: top_ranking(cfg.get("top_n", 5)),
                                              "chips_ranking.json", label="TWSE ranking")
    log(f"  ranking: {'ok' if ranking else 'unavailable'}{' [cache]' if used else ''}")

    watchlist = []
    for stock in cfg.get("watchlist", []):
        stock["id"] = str(stock["id"])
        data, used = fetch_with_cache_fallback(lambda s=stock: stock_detail(s),
                                               f"chips_stock_{stock['id']}.json", label=f"FinMind {stock['id']}")
        log(f"  {stock['id']} {stock['name']}: {'ok' if data else 'unavailable'}{' [cache]' if used else ''}")
        if data:
            watchlist.append(data)

    save_json(os.path.join(RAW_DIR, "chips.json"),
              {"market": {"totals": totals, "ranking": ranking}, "watchlist": watchlist})
    log("chips.json written")


if __name__ == "__main__":
    main()
