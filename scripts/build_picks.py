"""Check every stock against six analysts' published swing-trade rules and
write the result, encrypted, to docs/picks/data.json for the password page.

Ground rule (from the owner): only conditions with a clear public source are
judged automatically. A condition the source states without a number is shown
as data for the owner to judge ("judge"); one that needs broker-branch data
is flagged for the trading app ("manual"). No invented thresholds.

Prices are unadjusted (未還原), the default in most Taiwanese charting apps.

Reads data/stocks/daily/*.json + data/stocks/names.json (fetch_stock_history.py).
Needs PICKS_PASSWORD in the environment; without it nothing is written.
"""
import base64
import glob
import json
import os
import statistics
import sys
import zlib
from datetime import date as Date

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, log, load_json, now_taipei
import volume_surge

DAILY_DIR = os.path.join(DATA_DIR, "stocks", "daily")
OUT_PATH = os.path.join(ROOT, "docs", "picks", "data.json")
PBKDF2_ITER = 250_000
WEEKS_SHOWN = 26

AUTO, JUDGE, MANUAL = "auto", "judge", "manual"

# Order of checks here == order of [ok, detail] pairs in each stock's result.
ANALYSTS = [
    {"key": "zhu", "name": "朱家泓", "style": "技術分析・回後買上漲",
     "sources": [
         {"t": "今周刊 2016/8/15 選股條件", "u": "https://www.businesstoday.com.tw/article/category/80402/post/201608150006/"},
         {"t": "FTNN 回後買上漲（你提供的整理）"},
     ],
     "checks": [
         (AUTO, "當天漲幅 ≥ 3.5%"),
         (AUTO, "收紅 K（收盤高於開盤）"),
         (AUTO, "5 日 > 10 日 > 20 日線（多頭排列）"),
         (AUTO, "收盤站上月線（20 日線）"),
         (AUTO, "5 日線上彎"),
         (AUTO, "成交量 > 20 日均量"),
         (JUDGE, "底底高（回檔不破前低）"),
     ]},
    {"key": "lin", "name": "林恩如", "style": "20 週均線",
     "note": "原文說四個條件要同時符合，缺一不可。",
     "sources": [
         {"t": "經濟日報 2025/12/30 四大進場條件", "u": "https://udn.com/news/story/12806/9230636"},
         {"t": "CMoney 林恩如 淘寶好時機", "u": "https://www.cmoney.tw/notes/note-detail.aspx?nid=14195"},
     ],
     "checks": [
         (AUTO, "週收盤站上 20 週均線"),
         (JUDGE, "W 底（第二個底比第一個底高）"),
         (JUDGE, "當週爆量"),
         (MANUAL, "突破趨勢線"),
     ]},
    {"key": "warrant", "name": "權證小哥", "style": "布林通道＋籌碼",
     # The source describes two separate situations (narrow band about to open,
     # vs. a steep 20MA uptrend); requiring both on the same day almost never
     # happens, so either group passing counts.
     "groups": {"A": "布林開口買點", "B": "多頭趨勢"},
     "note": "原文是兩種不同情境：A 組「帶寬窄、開布林買進」，B 組「月線斜率陡、股價在上通道跟月線之間震盪是多頭」。任一組全過就算符合。",
     "sources": [
         {"t": "CMoney 2021/3/11 布林通道選股", "u": "https://www.cmoney.tw/notes/note-detail.aspx?nid=253723"},
         {"t": "Smart 自學網 進出場（你提供的整理）"},
     ],
     "checks": [
         (AUTO, "前一天布林帶寬 ≤ 5%", "A"),
         (AUTO, "布林開口（今天帶寬比昨天寬）", "A"),
         (AUTO, "月線斜率 ≥ 0.4%", "B"),
         (AUTO, "收盤站上月線，且月線往上", "B"),
         (JUDGE, "投信買超"),
         (MANUAL, "主力（券商分點）連續買超"),
     ]},
    {"key": "zhang", "name": "張志誠", "style": "季線翻揚＋右肩突破",
     "sources": [{"t": "中時 2026/9/30（你提供的整理）"}],
     "checks": [
         (AUTO, "季線（60 日線）翻揚向上"),
         (JUDGE, "右肩突破、創波段新高"),
         (JUDGE, "成交量放大"),
     ]},
    {"key": "chen", "name": "陳學進", "style": "低接不追高",
     "sources": [{"t": "鉅亨網 2026/9/29（你提供的整理）"}],
     "checks": [
         (AUTO, "守住 10 日線"),
         (AUTO, "守住月線（20 日線）"),
         (AUTO, "守住季線（60 日線）"),
         (JUDGE, "低接不追高"),
         (JUDGE, "量能守穩"),
     ]},
    {"key": "tsai", "name": "蔡正華", "style": "KD 強勢鈍化",
     "sources": [{"t": "中時 2026/9/24（你提供的整理）"}],
     "checks": [
         (AUTO, "日 KD 的 K 值 ≥ 80"),
     ]},
]


# ---------- formatting ----------

def p(x):
    """Price as the exchange prints it: up to 2 decimals, no trailing zeros."""
    if x is None:
        return "—"
    s = f"{x:,.2f}".rstrip("0").rstrip(".")
    return s


def pct(x, sign=True):
    return "—" if x is None else (f"{x:+.2f}%" if sign else f"{x:.2f}%")


def lots(x):
    return "—" if x is None else f"{x:,.0f} 張"


def md(iso):
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


# ---------- indicators ----------

def ma(arr, n, i=None):
    i = len(arr) - 1 if i is None else i
    if i < n - 1:
        return None
    return sum(arr[i - n + 1:i + 1]) / n


def kd_series(h, l, c, n=9):
    """Taiwan-style KD(9,3,3): K = 2/3 K' + 1/3 RSV, D = 2/3 D' + 1/3 K, seeded at 50."""
    k = d = 50.0
    ks, ds = [], []
    for i in range(len(c)):
        if i < n - 1:
            ks.append(None)
            ds.append(None)
            continue
        hi, lo = max(h[i - n + 1:i + 1]), min(l[i - n + 1:i + 1])
        rsv = 50.0 if hi == lo else (c[i] - lo) / (hi - lo) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        ks.append(k)
        ds.append(d)
    return ks, ds


def bollinger(c, i, n=20):
    if i < n - 1:
        return None
    win = c[i - n + 1:i + 1]
    mid = sum(win) / n
    sd = statistics.pstdev(win)
    up, lo = mid + 2 * sd, mid - 2 * sd
    return {"up": up, "mid": mid, "lo": lo, "bw": (up - lo) / mid * 100}


def weekly(dates, o, h, l, c, v):
    weeks = []
    for i, iso in enumerate(dates):
        y, w, _ = Date.fromisoformat(iso).isocalendar()
        if weeks and weeks[-1]["key"] == (y, w):
            wk = weeks[-1]
            wk["h"], wk["l"] = max(wk["h"], h[i]), min(wk["l"], l[i])
            wk["c"], wk["v"], wk["days"], wk["end"] = c[i], wk["v"] + v[i], wk["days"] + 1, iso
        else:
            weeks.append({"key": (y, w), "o": o[i], "h": h[i], "l": l[i], "c": c[i], "v": v[i],
                          "days": 1, "start": iso, "end": iso})
    closes = [wk["c"] for wk in weeks]
    for i, wk in enumerate(weeks):
        wk["ma20"] = ma(closes, 20, i)
    return weeks


# ---------- the six analysts ----------

NA = "資料不足"


def check_stock(s):
    dates, o, h, l, c, chg, v, tr = (s[k] for k in ("dates", "o", "h", "l", "c", "chg", "v", "trust"))
    n = len(c)
    i = n - 1
    ma5, ma10, ma20, ma60 = ma(c, 5), ma(c, 10), ma(c, 20), ma(c, 60)
    ma5_y, ma20_y, ma60_y = ma(c, 5, i - 1), ma(c, 20, i - 1), ma(c, 60, i - 1)
    vma20 = ma(v, 20)
    vma5 = ma(v, 5)
    prev_ref = c[i] - chg[i] if chg[i] is not None else None
    gain = chg[i] / prev_ref * 100 if prev_ref else None
    out = {}

    def need(*xs):
        return all(x is not None for x in xs)

    # 朱家泓
    zhu = []
    zhu.append([gain >= 3.5, f"當天漲幅 {pct(gain)}（門檻 +3.5%）"] if gain is not None
               else [None, "交易所沒給漲跌價差（可能是除權息日），無法計算漲幅"])
    body = (c[i] - o[i]) / o[i] * 100 if o[i] else 0
    zhu.append([c[i] > o[i], f"開 {p(o[i])} → 收 {p(c[i])}，實體 {pct(body)}"
                + ("。原文說十字線不算，實體夠不夠大請你判斷" if c[i] > o[i] else "")])
    zhu.append([ma5 > ma10 > ma20, f"5 日 {p(ma5)}／10 日 {p(ma10)}／20 日 {p(ma20)}"]
               if need(ma5, ma10, ma20) else [None, NA])
    zhu.append([c[i] > ma20, f"收 {p(c[i])}／月線 {p(ma20)}"] if need(ma20) else [None, NA])
    zhu.append([ma5 > ma5_y, f"5 日線 {p(ma5_y)} → {p(ma5)}"] if need(ma5, ma5_y) else [None, NA])
    zhu.append([v[i] > vma20, f"今天 {lots(v[i])}／20 日均量 {lots(vma20)}（{v[i] / vma20:.2f} 倍）"]
               if need(vma20) and vma20 else [None, NA])
    if n >= 40:
        a = min(range(i - 19, i + 1), key=lambda j: l[j])
        b = min(range(i - 39, i - 19), key=lambda j: l[j])
        zhu.append([None, f"近 20 日最低 {p(l[a])}（{md(dates[a])}）／再往前 20 日最低 {p(l[b])}（{md(dates[b])}）"])
    else:
        zhu.append([None, NA])
    out["zhu"] = {"c": zhu, "exit": (
        f"停損：進場 K 棒最低點 {p(l[i])}（今周刊）；或進場價 −5% ≈ {p(c[i] * 0.95)}（FTNN）。"
        + (f"停利：跌破 5 日線（目前 {p(ma5)}）出場（FTNN）" if ma5 else ""))}

    # 林恩如
    wks = weekly(dates, o, h, l, c, v)
    wk = wks[-1]
    partial = "（本週到 " + md(wk["end"]) + "，還沒收完）" if Date.fromisoformat(wk["end"]).weekday() < 4 else ""
    lin = []
    lin.append([wk["c"] > wk["ma20"], f"本週收 {p(wk['c'])}／20 週線 {p(wk['ma20'])}{partial}"]
               if wk["ma20"] is not None else [None, f"{NA}（需要 20 週，目前 {len(wks)} 週）"])
    lin.append([None, "看下方週 K 線圖自己判斷"])
    if len(wks) >= 5:
        prev4 = wks[-5:-1]
        avg_prev = sum(x["v"] for x in prev4) / sum(x["days"] for x in prev4)
        avg_now = wk["v"] / wk["days"]
        lin.append([None, f"本週日均量 {lots(avg_now)}／前 4 週日均量 {lots(avg_prev)}"
                          f"（{avg_now / avg_prev:.2f} 倍）。原文沒說幾倍算爆量" if avg_prev else NA])
    else:
        lin.append([None, NA])
    lin.append([None, "請在看盤軟體確認"])
    out["lin"] = {"c": lin, "exit": f"跌破 20 週線（目前 {p(wk['ma20'])}）出場" if wk["ma20"] else ""}
    shown = wks[-WEEKS_SHOWN:]
    out["lin"]["wk"] = [[md(x["end"]), x["o"], x["h"], x["l"], x["c"],
                         round(x["ma20"], 2) if x["ma20"] is not None else None] for x in shown]

    # 權證小哥
    bb, bb_y = bollinger(c, i), bollinger(c, i - 1)
    w = []
    w.append([bb_y["bw"] <= 5, f"前一天帶寬 {pct(bb_y['bw'], False)}（門檻 5%）"] if bb_y else [None, NA])
    w.append([bb["bw"] > bb_y["bw"], f"帶寬 {pct(bb_y['bw'], False)} → {pct(bb['bw'], False)}。"
                                     f"上軌 {p(bb['up'])}／中軌 {p(bb['mid'])}／下軌 {p(bb['lo'])}"]
             if bb and bb_y else [None, NA])
    slope = (ma20 / ma20_y - 1) * 100 if need(ma20, ma20_y) else None
    w.append([slope >= 0.4, f"月線 {p(ma20_y)} → {p(ma20)}，一天 {pct(slope)}（門檻 +0.4%）"]
             if slope is not None else [None, NA])
    w.append([c[i] > ma20 and ma20 > ma20_y, f"收 {p(c[i])}／月線 {p(ma20)}，月線{'往上' if ma20 > ma20_y else '沒有往上'}"]
             if need(ma20, ma20_y) else [None, NA])
    recent = [(dates[j], tr[j]) for j in range(max(0, i - 4), i + 1)]
    if all(t is not None for _, t in recent):
        days = "、".join(f"{md(d)} {t:+,}" for d, t in reversed(recent))
        w.append([None, f"近 5 日投信（張）：{days}；合計 {sum(t for _, t in recent):+,} 張。原文沒說看幾天"])
    else:
        w.append([None, "投信資料不完整"])
    w.append([None, "請在看盤軟體確認"])
    out["warrant"] = {"c": w, "exit": (
        f"停損 −10% ≈ {p(c[i] * 0.9)}、停利 +30% ≈ {p(c[i] * 1.3)}；"
        + (f"月線走平或下彎、跌破月線（目前 {p(ma20)}）出場" if ma20 else ""))}

    # 張志誠
    zh = []
    zh.append([ma60 > ma60_y, f"季線 {p(ma60_y)} → {p(ma60)}"] if need(ma60, ma60_y) else [None, NA])
    highs = []
    for span in (60, 120):
        if n >= span:
            j = max(range(i - span + 1, i + 1), key=lambda k: c[k])
            highs.append(f"近 {span} 日最高收盤 {p(c[j])}（{md(dates[j])}）")
    zh.append([None, f"收 {p(c[i])}；" + "；".join(highs) + "。原文沒說波段看多久" if highs else NA])
    zh.append([None, f"今天 {lots(v[i])}，是 20 日均量的 {v[i] / vma20:.2f} 倍。原文沒說幾倍" if vma20 else NA])
    out["zhang"] = {"c": zh, "exit": ""}

    # 陳學進
    ch = []
    for m, label in ((ma10, "10 日線"), (ma20, "月線"), (ma60, "季線")):
        ch.append([c[i] >= m, f"收 {p(c[i])}／{label} {p(m)}"] if m is not None else [None, NA])
    ch.append([None, f"收盤離 10 日線 {pct((c[i] / ma10 - 1) * 100)}。原文沒說多遠算追高" if ma10 else NA])
    ch.append([None, f"近 5 日均量 {lots(vma5)}／20 日均量 {lots(vma20)}（{vma5 / vma20:.2f} 倍）" if vma20 else NA])
    out["chen"] = {"c": ch, "exit": "跌破均線就減碼"}

    # 蔡正華
    ks, ds = kd_series(h, l, c)
    if n >= 30:  # give the K/D smoothing a few weeks to settle
        last5 = "、".join(f"{md(dates[j])} {ks[j]:.1f}" for j in range(i, max(i - 5, 0), -1))
        ts = [[ks[i] >= 80, f"K {ks[i]:.1f}／D {ds[i]:.1f}（門檻 80）。近 5 日 K：{last5}。原文說「站穩」，沒說幾天"]]
    else:
        ts = [[None, NA]]
    out["tsai"] = {"c": ts, "exit": ""}
    return out


# ---------- load / encrypt / write ----------

def load_series():
    files = sorted(glob.glob(os.path.join(DAILY_DIR, "*.json")))
    if not files:
        raise SystemExit("no daily files — run fetch_stock_history.py first")
    series = {}
    for f in files:
        day = load_json(f)
        for code, (o, h, l, c, chg, v, tr) in day["stocks"].items():
            s = series.setdefault(code, {k: [] for k in ("dates", "o", "h", "l", "c", "chg", "v", "trust")})
            for k, x in zip(("dates", "o", "h", "l", "c", "chg", "v", "trust"), (day["date"], o, h, l, c, chg, v, tr)):
                s[k].append(x)
    return series, load_json(files[-1])["date"], len(files)


def encrypt(payload, password):
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, zlib.compress(payload, 9), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "iter": PBKDF2_ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def build():
    series, latest, n_days = load_series()
    names = load_json(os.path.join(DATA_DIR, "stocks", "names.json"), {})
    shares = load_json(volume_surge.SHARES_PATH, {})
    stocks = {}
    for code, s in series.items():
        if s["dates"][-1] != latest:
            continue  # suspended / delisted: no quote on the latest day
        i = len(s["c"]) - 1
        chg = s["chg"][i]
        prev = s["c"][i] - chg if chg is not None else None
        name, market = names.get(code, ["", ""])
        stocks[code] = {"n": name, "m": market, "c": s["c"][i], "chg": chg,
                        "pct": round(chg / prev * 100, 2) if prev else None,
                        "days": len(s["c"]), "a": check_stock(s)}
        vi = volume_surge.vol_info(s["v"], shares.get(code))
        stocks[code]["vol"] = {**vi, "tags": volume_surge.tags(vi), "hit": volume_surge.is_ordinary(code) and volume_surge.qualifies(vi),
                               "thin": vi["v"] < volume_surge.MIN_LOTS and volume_surge.meets_standard(vi)}
    meta = [{**a, "checks": [{"t": c[0], "l": c[1], **({"g": c[2]} if len(c) > 2 else {})} for c in a["checks"]]}
            for a in ANALYSTS]
    surge = volume_surge.analyze(series, latest, names)
    return {"date": latest, "history_days": n_days, "generated_at": now_taipei().isoformat(timespec="minutes"),
            "analysts": meta, "stocks": stocks, "surge": [r["code"] for r in surge["rows"]]}


def main():
    data = build()
    log(f"picks: {len(data['stocks'])} stocks checked, data as of {data['date']} ({data['history_days']} trading days)")
    password = os.environ.get("PICKS_PASSWORD")
    if not password:
        log("WARN PICKS_PASSWORD not set — docs/picks/data.json left unchanged")
        return
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    out = {"date": data["date"], **encrypt(payload, password)}
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f)
    log(f"docs/picks/data.json written ({len(payload) / 1e6:.1f} MB raw → {os.path.getsize(OUT_PATH) / 1e6:.2f} MB encrypted)")


if __name__ == "__main__":
    main()
