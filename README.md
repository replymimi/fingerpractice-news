# 財經晨讀 fingerpractice-news

每天自動彙整國外股市／總經、加密貨幣新聞與 YouTube 頻道重點，翻譯成中文、抓出 4-5 個重點，
產生一個可以看也可以用手機朗讀聽的網頁。正式網址：https://news.fingerpractice.com

## 運作方式

一個 GitHub Actions 排程，一天跑兩次（台北時間）：

- **07:00 主更新**：抓新聞 RSS、大盤指數、潮汐板塊資料、除游庭皓以外的 YouTube 頻道 → AI 翻譯摘要 → 產生網頁
- **10:00 補充更新**：只補抓游庭皓的財經皓角（他 08:30-09:30 直播，07:00 時影片還沒上架）→ 合併進當天的頁面

## 目錄結構

```
sources.yaml              所有內容來源設定（要加減來源改這裡就好，不用碰程式）
scripts/
  common.py                共用工具（路徑、時區、快取容錯）
  fetch_news.py             抓 RSS 新聞
  fetch_market.py           抓大盤指數（道瓊/標普/那斯達克/SOX/TAIEX/TPEx/台幣匯率）
  fetch_tide.py              抓潮汐的板塊資金流向、大戶異常、情緒指數
  fetch_youtube.py           檢查頻道新影片、抓英文字幕
  summarize.py               AI 翻譯 + 抓重點，組成 summary.json
  build_page.py               把 summary.json 套進網頁樣板，輸出 docs/index.html
templates/index_template.html  網頁樣板
docs/                      GitHub Pages 發布的資料夾（index.html + CNAME）
data/
  raw/                     每次抓到的原始資料（有存進 git，讓 10:00 補充更新看得到 07:00 抓到的東西）
  cache/                   每個來源各自的「上一次成功結果」，來源掛掉時的備援
  processed/               summary.json，AI 處理完的最終資料（不進 git，每次重新產生）
```

## 容錯設計

每個新聞來源、每個 YouTube 頻道、每個指數，都是**各自獨立抓取**。任何一個來源當天壞掉、
抓不到，就用它自己上一次成功的快取頂著，不會讓整個版面空白或整個排程失敗。

板塊資金流向、大戶異常、情緒指數這幾個功能引用自 [Tide 潮汐](https://tide-tw.app/)
——一個獨立開發者做的公開資料，不是正式 API，所以一樣有快取備援；如果哪天他們調整了
資料格式或網址，這幾個區塊會先顯示上一次抓到的內容，而不是整個壞掉。

## 需要的密鑰（GitHub repo Secrets）

- `OPENAI_API_KEY` — 翻譯與摘要用
- `YOUTUBE_API_KEY` — 檢查頻道新影片、抓影片時長用（YouTube Data API v3，免費額度足夠）

## 本機測試

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/fetch_news.py      # 不需要金鑰
python scripts/fetch_market.py    # 不需要金鑰
python scripts/fetch_tide.py      # 不需要金鑰
export OPENAI_API_KEY=...
python scripts/summarize.py
python scripts/build_page.py      # 輸出 docs/index.html
```
