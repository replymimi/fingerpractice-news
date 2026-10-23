# 給接手這個 repo 的 agent

這是「財經晨讀」（news.fingerpractice.com）：每天自動彙整財經新聞、大盤、台股籌碼，並有私人的波段條件檢查頁（`/picks/`）。
它是手指練銀槍的**姊妹專案**，跟官網 repo `replymimi/fingerpractice-site`（本機 `~/Documents/手指練銀槍作品集`）分開，**不要合併**（2026-10-23 作者決定：news 的機器人每天自動 commit，合進官網會每次觸發官網部署）。

## 進度：先讀 `PROGRESS.md`，做完更新它

家裡 Mac、公司電腦的 Claude Code，和 claude.ai/code 雲端對話，**共用 `PROGRESS.md` 當這個專案唯一的進度來源**。
- **開工：** `git pull`，讀 `PROGRESS.md`。
- **收工（或作者做了決定）：** 更新 `PROGRESS.md`（最後更新日期、正在進行、等作者決定、最近發生的事），commit＋push。沒 push 就等於另一邊不知道。
- 作者會在家裡 Mac、公司電腦、手機之間切換，要求「同步接軌」：決定、設定變更、東西放在哪、怎麼重建，都要寫進 repo 再 push。只在對話裡講過，不算記下。
- 鑰匙（GitHub Secrets、FinMind、YouTube、密碼）只寫「放在哪、怎麼重拿」，不寫內容，不 commit。

## 跟官網專案共用的規則（作者的規則，這邊一樣適用）

- 一律用繁體中文、白話文跟作者說明；作者不是工程師，用比喻，少用術語。中英文與數字之間加半形空格。
- 執行重要開發行動前，先輸出簡要計劃，等作者確認再做。信心度低就上網研究後直接提建議。
- 時間一律台北時間（Asia/Taipei），涉及日期的操作前先跑 `date`。
- 要作者動作的事用 Telegram（只有家裡 Mac 有鑰匙：`~/Documents/手指練銀槍作品集/scripts/mac/tg_notify.sh "訊息"`），一則只講一件事、用「•」分行、開頭寫【期限】要你做什麼。公司電腦和雲端沒有鑰匙，改寄信並在 `PROGRESS.md` 註明「待家裡 Mac 補發 Telegram」。
- 發錯就發【更正】，說清楚錯在哪、正確是什麼。
- 不要用 `git commit -a`，只 add 這次真的要提交的檔案。
- **資料新鮮度（最重要）**：讀者會拿這些內容做判斷，備援快取不能默默頂替過期資料。詳見 `README.md`「資料新鮮度規則」。新增或更換來源後，要用第二個來源對照過數字與日期才算完成。

## 這個專案的特殊情況

- **機器人會自己 commit**：GitHub Actions 每天跑（07:00 主更新、10:00 補充、00:07 寄進場清單），commit 訊息開頭是 🤖。**push 前先 `git pull --rebase`**，不然會跟機器人撞。
- push 到 `main` 會讓 GitHub Pages 更新 news.fingerpractice.com。只改說明文件（`*.md`）不影響網頁。
- 改程式（`scripts/`、`templates/`、workflow）會影響明天早上的晨讀，改完要實際跑過、確認輸出正常再 push。
- 專案怎麼運作、目錄結構、設定步驟：`README.md`。

## 已停用

ChatGPT／OpenAI／Codex 在作者的整體環境已全面停用。**但這個專案的 `scripts/summarize.py` 還在用 OpenAI（gpt-4o-mini）做翻譯摘要**，換成 Claude 要作者決定（見 `PROGRESS.md`「等作者決定」），不要自己偷偷改。
