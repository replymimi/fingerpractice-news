"""Turn the raw fetched data into Chinese, bullet-point content the page can
render. Two kinds of AI calls:

  - per-item summarize: translate a title + extract 4-5 bullets from a single
    news article or video transcript (grounded in that item's own text only)
  - recap bullets: a short analysis for the 美股/台股 columns, grounded in the
    real index numbers + Tide sector data + the day's own fetched headlines
    (never invented causes — only what the fetched text actually supports)

Writes data/processed/summary.json, which build_page.py renders as-is.
"""
import html
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW_DIR, DATA_DIR, TAIPEI, log, load_json, save_json

PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
os.makedirs(PROCESSED_DIR, exist_ok=True)

from openai import OpenAI

MODEL = "gpt-4o-mini"
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _client


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def ai_json(prompt, *, max_points=5):
    """One JSON-mode call. Returns the parsed dict, or None on any failure —
    callers must handle None by falling back to a title-only entry rather
    than crashing the whole run over one bad item."""
    try:
        resp = get_client().chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": (
                    "你是財經新聞編輯，任務是把英文內容整理成繁體中文重點，給讀者看重點就不用點開原文/原片。"
                    "只根據使用者提供的原文內容整理，不要加入原文沒有的事實、數字或臆測原因。"
                    "重點必須具體、可驗證，不能只寫抽象方向。"
                    "原文提到的公司名、股票代號、ETF 代號、具體數字（價位、漲跌幅、百分比、金額）、"
                    "日期、產品名稱，只要出現在原文裡，就要盡量保留在摘要裡，不要抽象化成「相關類股」"
                    "「某些公司」「未來可能」這種空話。"
                    "反面例子（禁止這樣寫）：「AI發展的潛在風險與機會，可能影響投資決策」。"
                    "正確示範（要這樣寫）：「作者看好網路安全需求，買進軟體 ETF IGV，而非直接買 "
                    "CrowdStrike(CRWD)或 Palo Alto Networks(PANW)」——後者才是讀者真正想看到的內容。"
                    f"輸出 JSON，格式為 {{\"title_zh\": \"...\", \"points\": [\"...\", ...]}}，"
                    f"points 最多 {max_points} 條、每條 15-35 字。這是上限不是目標，"
                    "原文如果只夠寫 4 條扎實的重點，就寫 4 條就好，不要為了湊到上限而把同一件事拆成兩條、"
                    "或加入無關緊要的細節硬湊數量；每一條都要是獨立、有新資訊的重點。"
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            timeout=45,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        log(f"    AI call failed: {e}")
        return None


def summarize_news_item(item):
    body = strip_html(item.get("summary_raw", ""))
    prompt = f"來源：{item['source']}\n標題：{item['title']}\n內文摘要：{body}"
    result = ai_json(prompt)
    if not result:
        return {
            "source": item["source"], "title_zh": item["title"],
            "points": ["（此則暫時無法自動摘要，請點連結看原文）"],
            "link": item.get("link", ""), "published_iso": item.get("published_iso"),
        }
    return {
        "source": item["source"], "title_zh": result.get("title_zh", item["title"]),
        "points": result.get("points", []), "link": item.get("link", ""),
        "published_iso": item.get("published_iso"),
    }


def summarize_video_item(item):
    transcript = item.get("transcript_raw", "")
    if transcript:
        prompt = f"來源頻道：{item['source']}\n影片標題：{item['title']}\n英文字幕內容：{transcript}"
    else:
        prompt = (f"來源頻道：{item['source']}\n影片標題：{item['title']}\n"
                   "（沒有取得字幕，只能依標題判斷，points 請控制在 2 條以內，且語氣保守）")
    result = ai_json(prompt, max_points=15 if transcript else 2)
    if not result:
        return {
            "source": item["source"], "title_zh": item["title"],
            "points": ["（此則暫時無法自動摘要，請點連結看原片）"],
            "video_url": item.get("video_url", ""), "published_iso": item.get("published_iso"),
            "duration": item.get("duration", ""),
        }
    return {
        "source": item["source"], "title_zh": result.get("title_zh", item["title"]),
        "points": result.get("points", []), "video_url": item.get("video_url", ""),
        "published_iso": item.get("published_iso"), "duration": item.get("duration", ""),
    }


def build_market_tiles(rows):
    tiles = []
    for row in rows:
        is_currency = row.get("is_currency")
        if is_currency:
            tiles.append({
                "name": row["name"], "value": f"{row['price']:.3f}",
                "direction": "up" if row["chg"] >= 0 else "down",
                "change_label": f"{'升值' if row['chg'] >= 0 else '貶值'} {abs(row['chg']):.3f}",
            })
        else:
            sign = "+" if row["chg"] >= 0 else ""
            tiles.append({
                "name": row["name"], "value": f"{row['price']:,.2f}",
                "direction": "up" if row["chg"] >= 0 else "down",
                "change_label": f"{sign}{row['chg']:,.2f}（{sign}{row['chg_pct']:.2f}%）",
            })
    return tiles


def sector_flow_ranking(tide_latest):
    if not tide_latest or "sectors" not in tide_latest:
        return {"inflow": [], "outflow": [], "as_of": None}
    sectors = sorted(tide_latest["sectors"], key=lambda s: s["net_5d_yi"], reverse=True)
    inflow = [{"name": s["name"], "amount": s["net_5d_yi"]} for s in sectors[:5]]
    outflow = [{"name": s["name"], "amount": s["net_5d_yi"]} for s in sectors[-5:][::-1] if s["net_5d_yi"] < 0]
    return {"inflow": inflow, "outflow": outflow, "as_of": tide_latest.get("date")}


def whale_activity(tide_digest):
    if not tide_digest or "big_money" not in tide_digest:
        return {"buy": [], "sell": []}
    bm = tide_digest["big_money"]
    buy = [{"name": s["name"], "amount": s["net_1d_yi"]} for s in bm.get("abnormal_buy", [])[:3]]
    sell = [{"name": s["name"], "amount": s["net_1d_yi"]} for s in bm.get("abnormal_sell", [])[:3]]
    return {"buy": buy, "sell": sell}


def sentiment_gauge(tide_digest):
    if not tide_digest or "panic_index" not in tide_digest:
        return None
    p = tide_digest["panic_index"]
    # our gauge runs 樂觀(0%) -> 恐慌(100%); Tide's score is already on that scale
    return {
        "score": p["score"], "label": p["label"],
        "advancers": p["advancers"], "decliners": p["decliners"],
        "marker_pct": p["score"],
    }


def recap_bullets(region_label, market_rows, tide_sentence, headlines):
    lines = [f"{r['name']}: {r['price']:,.2f} ({r['chg_pct']:+.2f}%)" for r in market_rows]
    headline_block = "\n".join(f"- {h}" for h in headlines[:6]) or "（無）"
    prompt = (
        f"以下是{region_label}最新的指數數據：\n" + "\n".join(lines) + "\n\n"
        f"{tide_sentence}\n\n"
        f"以下是同一批的新聞標題，只能用這些做為推論依據，不要引用清單外的事件：\n{headline_block}\n\n"
        "請根據以上資料寫 4-5 條重點，描述目前市場狀況；"
        "如果新聞標題不足以解釋漲跌原因，就只描述數字本身、不要臆測原因。"
    )
    result = ai_json(prompt)
    if result and result.get("points"):
        return result.get("title_zh", f"{region_label}市場摘要"), result["points"]
    return f"{region_label}市場摘要", [f"{r['name']} 收在 {r['price']:,.2f}（{r['chg_pct']:+.2f}%）" for r in market_rows]


def main():
    news = load_json(os.path.join(RAW_DIR, "news.json"), {"stocks": [], "crypto": []})
    youtube = load_json(os.path.join(RAW_DIR, "youtube.json"), {"stocks": [], "crypto": []})
    market = load_json(os.path.join(RAW_DIR, "market.json"), {"us": [], "tw": []})
    tide = load_json(os.path.join(RAW_DIR, "tide.json"), {})

    log("Summarizing news items...")
    news_out = {col: [summarize_news_item(it) for it in news.get(col, [])] for col in ("stocks", "crypto")}

    log("Summarizing YouTube items...")
    youtube_out = {col: [summarize_video_item(it) for it in youtube.get(col, [])] for col in ("stocks", "crypto")}

    log("Building market tiles + Tide-derived sections...")
    tide_latest = tide.get("latest")
    tide_digest = tide.get("daily_digest")
    flow = sector_flow_ranking(tide_latest)
    whale = whale_activity(tide_digest)
    sentiment = sentiment_gauge(tide_digest)

    us_headlines = [it["title_zh"] for it in news_out["stocks"]]
    tw_context = ""
    if flow["inflow"]:
        top_in = "、".join(f"{s['name']}(+{s['amount']:.0f}億)" for s in flow["inflow"][:3])
        tw_context = f"近五日法人資金流入前三名板塊：{top_in}。"

    us_title, us_points = recap_bullets("美股", market.get("us", []), "", us_headlines)
    tw_title, tw_points = recap_bullets("台股", market.get("tw", []), tw_context, us_headlines)

    now = datetime.now(TAIPEI)
    summary = {
        "generated_at": now.isoformat(),
        "date_label": now.strftime("%Y/%m/%d") + f"（週{WEEKDAYS[now.weekday()]}）",
        "market": {
            "us_tiles": build_market_tiles(market.get("us", [])),
            "tw_tiles": build_market_tiles(market.get("tw", [])),
            "us_recap": {"title": us_title, "points": us_points},
            "tw_recap": {"title": tw_title, "points": tw_points},
        },
        "tide": {"flow": flow, "whale": whale, "sentiment": sentiment},
        "news": news_out,
        "youtube": youtube_out,
    }
    save_json(os.path.join(PROCESSED_DIR, "summary.json"), summary)
    log("summary.json written")


if __name__ == "__main__":
    main()
