# 財經晨讀 fingerpractice-news｜目前進度

> 這份是這個專案**唯一的進度來源**。家裡 Mac、公司電腦、claude.ai/code 的對話都讀這份。
> 規則：開工先 `git pull` 讀這份；做完事、作者做了決定，就更新這份再 commit＋push（push 前 `git pull --rebase`，機器人每天會自己 commit）。日期一律台北時間。
> 官網專案的進度在另一個 repo：`replymimi/fingerpractice-site` 的 `PROGRESS.md`。

最後更新：2026-10-23（五）12:00

## 專案在哪裡

| 項目 | 位置 |
|---|---|
| 網址 | https://news.fingerpractice.com （GitHub Pages，發布 `docs/`） |
| 私人頁 | `/picks/`（波段條件檢查，密碼加密，不被搜尋引擎收錄） |
| GitHub repo | `replymimi/fingerpractice-news`（私人） |
| 家裡 Mac 本機 | `~/Documents/Codex/fingerpractice-news` |
| 自動排程 | GitHub Actions：`update-main.yml`（台北 07:00 上線）、`update-supplemental.yml`（10:00 補游庭皓）、`send-watchlist.yml`（00:07 寄進場清單） |
| 金鑰 | 都在 GitHub Secrets（`OPENAI_API_KEY`、`YOUTUBE_API_KEY`、`SUPADATA_API_KEY`、`FINMIND_TOKEN`、`PICKS_PASSWORD`、`WATCHLIST_URL`）。不在 repo；要重拿就到各服務官網重新產生再貼回 Secrets |
| 怎麼運作、怎麼重建 | `README.md` |

## 在 claude.ai 側邊欄怎麼選

家裡 Mac 的 Claude App 把對話按資料夾分成兩個抽屜：**fingerpractice-news**（這個專案：新聞、選股、FinMind、儀表板、報價單相關）和 **fingerpractice-site**（官網、發文、週報、工作台）。要做 news 的事，就在 news 抽屜按「＋」；在 claude.ai/code 開雲端對話則選 `fingerpractice-news` 這個 repo。

## 正在進行

| 項目 | 狀態 | 細節 |
|---|---|---|
| 每日自動更新 | ✅ 運作中 | 最近一次機器人更新到 2026-10-22 的資料（10-23 11:30 `git pull` 確認）。 |

## 等作者決定

| 問題 | 期限 | 背景 |
|---|---|---|
| 翻譯摘要從 OpenAI 換成 Claude | **作者 10-23 決定：等 OpenAI 額度用完再換**，不急著動 | `scripts/summarize.py` 的 `ai_json()` 是唯一呼叫 AI 的地方（OpenAI `gpt-4o-mini`），GitHub Secrets 有 `OPENAI_API_KEY`。換法已跟作者講過：（1）作者到 console.anthropic.com 儲值、建金鑰、存進 GitHub Secrets `ANTHROPIC_API_KEY`（不貼給 Claude）（2）Claude 在分支改 `summarize.py`、`requirements.txt`、兩個 workflow，先用 `claude-haiku-5-5`（3）同一批資料新舊並排對照品質、實測費用，不夠好再試 Sonnet 5.5（4）作者說可以才合併，隔天 07:00 看晨讀，3 天沒事再刪 `OPENAI_API_KEY`。**額度用完前現況照跑，不要偷偷改。** |
| **額度用完的徵兆** | — | OpenAI 額度沒了，`ai_json()` 會失敗，晨讀每則會變成「（此則暫時無法自動摘要，請點連結看原文）」，頁面不會壞但沒有摘要。看到這個就是該換的時候，換的步驟照上一列。 |

## 最近發生的事（新的在上面）

- **10-23** 12:00 作者決定 OpenAI 換 Claude 這件事等額度用完再做（見上方「等作者決定」），計劃和步驟已記好。
- **10-23** 作者決定 news 和官網**不合併**、各自一個 repo（理由：機器人每天自動 commit，合進官網會每次觸發官網自動部署，繞過「改官網要作者確認」的規則）。改成兩邊各有 `PROGRESS.md`／`CLAUDE.md`，規則一致，三地都能接手。新增這份 `PROGRESS.md` 和 `CLAUDE.md`。順手發現上面「OpenAI 殘留」那件事。
