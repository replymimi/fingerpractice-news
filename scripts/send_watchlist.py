"""Email the owner's 「明天要進場」 watchlist with each stock's latest checks.

The list lives in a Google Apps Script web app (apps-script/Code.gs), which the
password page writes to. This script reads it, builds the email from the
results build_picks.py just computed (data/processed/picks.json), and asks the
same Apps Script to send it — so mail goes out from the owner's own Google
account and no mail password is stored anywhere.

Needs WATCHLIST_URL and PICKS_PASSWORD (also the Apps Script key). An empty
list sends nothing.
"""
import html
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, log, load_json

PAGE_URL = "https://news.fingerpractice.com/picks/"
HIGH = {60: "創 3 個月新高量", 120: "創半年新高量"}


def call(url, key, **body):
    r = requests.post(url, data=json.dumps({"key": key, **body}), timeout=60,
                      headers={"Content-Type": "text/plain;charset=utf-8"})
    r.raise_for_status()
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Apps Script: {j.get('error')}")
    return j


def auto_status(pairs):
    failed = sum(1 for _, r in pairs if r[0] is False)
    missing = sum(1 for _, r in pairs if r[0] is None)
    return ("fail", failed) if failed else ("na", 0) if missing else ("pass", 0)


def verdict(meta, res):
    """Same rules as the page: any group fully passing counts (權證小哥)."""
    pairs = [(m, res["c"][i]) for i, m in enumerate(meta["checks"])]
    open_items = [m["l"] for m in meta["checks"] if m["t"] != "auto"]
    autos = [(m, r) for m, r in pairs if m["t"] == "auto"]
    if meta.get("groups"):
        gs = {g: auto_status([(m, r) for m, r in autos if m.get("g") == g]) for g in meta["groups"]}
        passed = [g for g, (k, _) in gs.items() if k == "pass"]
        if passed:
            who = "兩組都全過" if len(passed) == len(gs) else f"{'、'.join(passed)} 組全過"
            return "pass", who, open_items
        if all(k == "fail" for k, _ in gs.values()):
            return "fail", "兩組都不符合（" + "、".join(f"{g} 組卡 {n} 條" for g, (_, n) in gs.items()) + "）", open_items
        return "na", "資料不足", open_items
    k, n = auto_status(autos)
    if k == "fail":
        return "fail", f"不符合，卡 {n} 條", open_items
    if k == "na":
        return "na", "資料不足", open_items
    return "pass", "自動條件都過", open_items


def esc(x):
    return html.escape(str(x))


def vol_line(v):
    parts = [f"{v['v']:,} 張"]
    if v.get("m5") is not None:
        parts.append(f"前 5 日均量 {v['a5']:,}（{v['m5']} 倍）")
    if v.get("m20") is not None:
        parts.append(f"前 20 日均量 {v['a20']:,}（{v['m20']} 倍）")
    parts.append("週轉率 —" if v.get("turnover") is None else f"週轉率 {v['turnover']}%")
    return "／".join(parts)


def stock_block(item, data):
    code = item["code"]
    s = data["stocks"].get(code)
    note = f"<p style='margin:6px 0;color:#565F72'>備註：{esc(item['note'])}</p>" if item.get("note") else ""
    added = f"<span style='color:#8891A3;font-size:12px'>（{esc(item.get('added', ''))} 加入）</span>"
    if not s:
        return f"<h2 style='font-size:17px;margin:24px 0 4px'>{esc(code)} {added}</h2>{note}<p>找不到這檔 {esc(data['date'])} 的收盤資料（可能暫停交易或代號有誤）。</p>"

    chg = "" if s["chg"] is None else f" {s['chg']:+g}" + ("" if s["pct"] is None else f"（{s['pct']:+.2f}%）")
    out = [f"<h2 style='font-size:17px;margin:24px 0 4px'>{esc(code)} {esc(s['n'])} "
           f"<span style='font-weight:400;font-size:14px'>{esc(s['m'])}・收 {s['c']:g}{esc(chg)}</span> {added}</h2>", note]

    v = s.get("vol")
    if v:
        head = ("🔥 爆大量" + (f"：{'・'.join(v['tags'])}" if v["tags"] else "")) if v.get("hit") else \
               ("量能：倍數或週轉率有達標，但當天成交未滿 1,000 張" if v.get("thin") else "量能：沒有達到爆大量標準")
        out.append(f"<p style='margin:6px 0'><b>{esc(head)}</b><br><span style='color:#565F72;font-size:13px'>{esc(vol_line(v))}</span></p>")

    rows, exits = [], []
    for meta in data["analysts"]:
        res = s["a"][meta["key"]]
        k, text, open_items = verdict(meta, res)
        icon = {"pass": "✅", "fail": "❌", "na": "⚪"}[k]
        line = f"{icon} <b>{esc(meta['name'])}</b>：{esc(text)}"
        if k == "pass" and open_items:
            line += f"<br><span style='color:#565F72;font-size:13px'>待你確認：{esc('、'.join(open_items))}</span>"
        if k == "fail":
            fails = [f"{m['l']}（{r[1]}）" for m, r in zip(meta["checks"], res["c"]) if m["t"] == "auto" and r[0] is False]
            line += "".join(f"<br><span style='color:#B8342F;font-size:13px'>・{esc(f)}</span>" for f in fails)
        rows.append(f"<li style='margin:6px 0'>{line}</li>")
        if res.get("exit"):
            exits.append(f"<li style='margin:3px 0'>{esc(meta['name'])}：{esc(res['exit'])}</li>")
    out.append(f"<ul style='list-style:none;padding:0;margin:8px 0'>{''.join(rows)}</ul>")
    if exits:
        out.append(f"<p style='margin:10px 0 2px;font-size:13px'><b>出場參考</b></p>"
                   f"<ul style='margin:0;padding-left:18px;font-size:13px;color:#565F72'>{''.join(exits)}</ul>")
    return "".join(out)


def build_email(items, data):
    d = data["date"]
    md = f"{int(d[5:7])}/{int(d[8:10])}"
    subject = f"明天要進場 {len(items)} 檔｜{md} 收盤檢查"
    body = "".join(stock_block(it, data) for it in items)
    html_out = (
        "<div style='font-family:-apple-system,\"PingFang TC\",\"Noto Sans TC\",sans-serif;color:#12151C;max-width:640px;line-height:1.55'>"
        f"<p style='color:#565F72;font-size:13px;margin:0'>資料日期：{esc(d)} 收盤（共 {len(items)} 檔）・"
        f"<a href='{PAGE_URL}' style='color:#A9701A'>打開波段條件檢查頁</a></p>"
        f"{body}"
        "<hr style='border:none;border-top:1px solid #D6DBE4;margin:24px 0 10px'>"
        "<p style='color:#8891A3;font-size:12px'>這是公開資訊的條件整理，不是投資建議。只有原文有數字的條件才自動打勾；"
        "「待你確認」是原文沒給數字、或要看盤軟體的條件。股價為未還原價。清單要增減請到波段條件檢查頁。</p></div>"
    )
    return subject, html_out


def main():
    url, key = os.environ.get("WATCHLIST_URL"), os.environ.get("PICKS_PASSWORD")
    if not url or not key:
        log("WARN WATCHLIST_URL / PICKS_PASSWORD not set — watchlist email skipped")
        return
    data = load_json(os.path.join(DATA_DIR, "processed", "picks.json"))
    if not data:
        raise SystemExit("data/processed/picks.json missing — run build_picks.py first")
    items = call(url, key, action="list")["list"]
    if not items:
        log("watchlist is empty — no email")
        return
    subject, body = build_email(items, data)
    call(url, key, action="send", subject=subject, html=body)
    log(f"watchlist email sent: {subject}")


if __name__ == "__main__":
    main()
