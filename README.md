# 財經晨讀 fingerpractice-news

每天自動彙整國外股市／總經、加密貨幣新聞與 YouTube 頻道重點，翻譯成中文、抓出 4-5 個重點，
產生一個可以看也可以用手機朗讀聽的網頁。正式網址：https://news.fingerpractice.com

## 運作方式

一個 GitHub Actions 排程，一天跑兩次（台北時間）：

- **07:00 主更新**：抓新聞 RSS、大盤指數、潮汐板塊資料、台股法人籌碼與自選股、除游庭皓以外的 YouTube 頻道 → AI 翻譯摘要 → 產生網頁
- **10:00 補充更新**：只補抓游庭皓的財經皓角（他 08:30-09:30 直播，07:00 時影片還沒上架）→ 合併進當天的頁面

## 目錄結構

```
sources.yaml              所有內容來源設定（要加減來源改這裡就好，不用碰程式）
scripts/
  common.py                共用工具（路徑、時區、快取容錯）
  fetch_news.py             抓 RSS 新聞
  fetch_market.py           抓大盤指數（道瓊/標普/那斯達克/SOX/TAIEX/TPEx/台幣匯率）
  fetch_tide.py              抓潮汐的板塊資金流向、大戶異常、情緒指數
  fetch_chips.py             抓三大法人買賣超排行、融資融券、自選股（證交所 + FinMind）
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

### 資料新鮮度規則（最重要）

網站的讀者會拿這些內容做判斷，所以**備援快取不能默默頂替過期資料**：

- 新聞：超過 4 天的項目不顯示（`fetch_news.py` 的 `MAX_AGE_DAYS`）；某來源一則新的都沒有會在 log 印 WARN。
- 指數：每筆都帶 `as_of`（報價時間），快取備援超過 4 天就直接丟掉不顯示（`fetch_market.py` 的 `STALE_CACHE_DAYS`）。
- 頁面上：新聞和影片顯示「月/日（週）時間」，指數 tile 顯示資料時間。
- 新增或更換任何來源後，要用第二個來源（官方資料、另一個報價）對照過數字與日期，才算完成。
  歷史教訓：MarketWatch 凍結 11 天、Calculated Risk 停更 9 個月、櫃買指數凍結 3 週都沒被發現。

## 需要的密鑰（GitHub repo Secrets）

- `OPENAI_API_KEY` — 翻譯與摘要用
- `YOUTUBE_API_KEY` — 檢查頻道新影片、抓影片時長用（YouTube Data API v3，免費額度足夠）
- `PICKS_PASSWORD` — 波段條件檢查頁的密碼（見下方）。沒設定的話，那一頁就不會更新，晨讀本身不受影響
- `SUPADATA_API_KEY` — 抓影片字幕用。GitHub Actions 的雲端 IP 會被 YouTube 直接擋掉字幕請求（`RequestBlocked`），所以改用 [Supadata](https://supadata.ai) 這個第三方服務代抓，免費額度每月 100 次，只用「原生字幕」模式（不會誤觸每分鐘 2 credits 的 AI 轉錄模式），額度用完會自動退回只用標題摘要，不會整個壞掉

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

三大法人動向與自選股追蹤：全市場的外資／投信買賣超排行用[臺灣證券交易所](https://www.twse.com.tw/)的
公開資料（目前只含上市股票、排除 ETF，金額是「買賣超股數 × 收盤價」的估算）；大盤法人總額、融資融券、
自選股的股價、法人進出、月營收用 [FinMind](https://finmindtrade.com/)。FinMind 不註冊也能用（每小時 300 次），
想提高到 600 次，就到 FinMind 官網註冊拿 token，存成 GitHub Secrets 的 `FINMIND_TOKEN`。
自選股清單在 `sources.yaml` 的 `tw_chips.watchlist`。

## 波段條件檢查頁（私人，`/picks/`）

輸入台股代號，看 6 家名師（朱家泓、林恩如、權證小哥、張志誠、陳學進、蔡正華）的波段買點條件，
每家各自判斷「符合／不符合」，不符合會列出卡在哪一條、實際數字是多少。

- **規則原則**：只有原文有數字、或本來就是是非題的條件才自動打勾；原文沒給數字的條件只列數據，
  標「請你判斷」；要看券商分點的標「需看盤軟體」。**不自己補門檻數字。**規則和出處都寫在
  `scripts/build_picks.py` 最上面的 `ANALYSTS`。
- `scripts/fetch_stock_history.py`：每天抓證交所＋櫃買中心的全市場收盤行情和投信買賣超，
  每個交易日存一個檔（`data/stocks/daily/`），保留最近 150 個交易日。不花 AI token。
  第一次或資料缺很多天時：`python scripts/fetch_stock_history.py --backfill 150`（約 25 分鐘）。
- `scripts/build_picks.py`：算出全部股票的結果，用 `PICKS_PASSWORD` 加密成 `docs/picks/data.json`。
  網頁本身（`docs/picks/index.html`）是公開的空殼，沒有密碼就只看得到亂碼。
- 不讓搜尋引擎收錄：頁面有 `noindex`，`docs/robots.txt` 也擋掉 `/picks/`，首頁不放連結。
- 股價是未還原價。這兩步失敗不會擋住晨讀上線（workflow 設了 `continue-on-error`）。

### 爆大量

`scripts/volume_surge.py` 用同一份全市場資料挑出爆大量的普通股（排除 ETF），標準是**使用者自訂**：
成交量 ≥ 過去 5 日或 20 日均量的 2 倍（不含當天），或創 3 個月（60 日）新高量，或週轉率 > 10%，
任一成立、而且當天成交 ≥ 1,000 張（排除冷門股）就列入；≥ 3 倍、創半年新高量、週轉 > 20%／> 30%（籌碼不穩）另外標籤。週轉率用的發行股數
每天由 `fetch_stock_history.py` 抓（`data/stocks/shares.json`）。晨讀首頁顯示依倍數排序的 TOP 10
（清單超過 4 天就不顯示），密碼頁有完整清單和個股的量能資訊。

### 明天要進場清單（每天寄信）

密碼頁最上面的「明天要進場」清單存在使用者自己 Google 帳號的 Apps Script（`apps-script/Code.gs`），
手機和電腦共用。`scripts/send_watchlist.py` 讀清單、組好信，再請同一個
Apps Script 從使用者的 Google 帳號寄到 thisismimi.yu@gmail.com（收件人寫死在 Code.gs）。
寄信在獨立的 `send-watchlist.yml`，每天 00:07（台北）跑：當天收盤資料已經有了，就算 GitHub
排程延遲幾小時也會在開盤前寄到；同時更新波段條件檢查頁。
清單是空的那天不寄。清單會一直保留，要刪請到頁面上刪。

設定（一次）：
1. 到 script.google.com 新增專案，把 `apps-script/Code.gs` 全部貼上、存檔
2. 專案設定 → 指令碼屬性 → 新增 `KEY`，值跟 `PICKS_PASSWORD` 一樣
3. 函式選 `authorize` 按「執行」，允許寄信權限
4. 部署 → 新增部署作業 → 類型「網頁應用程式」，執行身分「我」，存取權「所有人」→ 複製網址
5. GitHub Secrets 新增 `WATCHLIST_URL` = 那個網址

改了 `PICKS_PASSWORD` 的話，Apps Script 的 `KEY` 也要一起改。
