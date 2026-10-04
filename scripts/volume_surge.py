"""Find stocks with a volume surge (爆大量) on the latest trading day.

The owner's own standard (自訂, not any analyst's or the exchange's):
  - 倍數: volume >= 2x the average of the PREVIOUS 5 or 20 trading days
    (today excluded, so the comparison is against the past)
  - 新高量: volume above every day of the previous 60 trading days (~3 months)
  - 週轉率: volume / issued common shares > 10%
Any one of the three puts a stock on the list, as long as the day's volume
is at least 1,000 張 (owner's choice, to drop thinly traded stocks where 120
張 can already be "18x"). Stronger levels become tags:
>= 3x, a 120-day (~half-year) high, turnover > 20%, and > 30% (chips unstable).

Only ordinary stocks (4-digit codes not starting with 0); ETFs are left out.

Writes data/raw/volume_surge.json (read by summarize.py for the brief's
TOP 10, and by build_picks.py for the full list on the private page).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, RAW_DIR, log, load_json, save_json

SHARES_PATH = os.path.join(DATA_DIR, "stocks", "shares.json")
MULT_MIN, MULT_STRONG = 2, 3
TURNOVER_MIN, TURNOVER_HIGH, TURNOVER_UNSTABLE = 10, 20, 30
MIN_LOTS = 1000  # day's volume floor, 張


def is_ordinary(code):
    return len(code) == 4 and code.isdigit() and not code.startswith("0")


def vol_info(v, shares):
    """Volume facts for one stock's latest day. v = daily volumes in 張, oldest first."""
    today = v[-1]
    past = v[:-1]
    info = {"v": today}
    for n in (5, 20):
        if len(past) >= n:
            avg = sum(past[-n:]) / n
            info[f"a{n}"] = round(avg)
            info[f"m{n}"] = round(today / avg, 2) if avg else None
    ms = [info.get("m5"), info.get("m20")]
    ms = [m for m in ms if m is not None]
    info["mult"] = max(ms) if ms else None
    info["high"] = 0
    for n in (120, 60):
        if len(past) >= n and today > max(past[-n:]):
            info["high"] = n
            break
    info["turnover"] = round(today * 1000 / shares * 100, 2) if shares else None
    return info


def meets_standard(info):
    return ((info["mult"] or 0) >= MULT_MIN or info["high"] >= 60
            or (info["turnover"] or 0) > TURNOVER_MIN)


def qualifies(info):
    return info["v"] >= MIN_LOTS and meets_standard(info)


def tags(info):
    out = []
    if (info["mult"] or 0) >= MULT_STRONG:
        out.append(f"≥ {MULT_STRONG} 倍")
    if info["high"] == 120:
        out.append("創半年新高量")
    elif info["high"] == 60:
        out.append("創 3 個月新高量")
    t = info["turnover"] or 0
    if t > TURNOVER_UNSTABLE:
        out.append(f"⚠️ 週轉 > {TURNOVER_UNSTABLE}% 籌碼不穩")
    elif t > TURNOVER_HIGH:
        out.append(f"週轉 > {TURNOVER_HIGH}%")
    return out


def analyze(series, latest, names):
    shares = load_json(SHARES_PATH, {})
    rows = []
    for code, s in series.items():
        if s["dates"][-1] != latest or not is_ordinary(code):
            continue
        info = vol_info(s["v"], shares.get(code))
        if not qualifies(info):
            continue
        chg, c = s["chg"][-1], s["c"][-1]
        prev = c - chg if chg is not None else None
        name, market = names.get(code, ["", ""])
        rows.append({"code": code, "name": name, "market": market, "close": c,
                     "pct": round(chg / prev * 100, 2) if prev else None,
                     **info, "tags": tags(info)})
    rows.sort(key=lambda r: r["mult"] or 0, reverse=True)
    return {"date": latest, "count": len(rows), "rows": rows}


def main():
    from build_picks import load_series
    series, latest, _ = load_series()
    names = load_json(os.path.join(DATA_DIR, "stocks", "names.json"), {})
    out = analyze(series, latest, names)
    save_json(os.path.join(RAW_DIR, "volume_surge.json"), out)
    log(f"volume surge: {out['count']} stocks on {latest}")


if __name__ == "__main__":
    main()
