# Codex 遊戲新聞審稿流程

這份流程給 Codex 自動化使用。Bilibili 影片不走這份流程，仍然由 GitHub Actions 無腦轉發。

## 最新工作結論

- 後續遊戲新聞日報、補檢、修正、追蹤與發送狀態回報都繼續在目前這個 Codex thread 處理，除非主人明確要求開新串。
- Bilibili 影片是無腦轉發：每小時掃描兩個頻道，有新 BV 就直接發 Discord，不審稿、不摘要、不點評。
- 遊戲新聞是 Codex 審稿制：候選清單只當素材，不可直接發規則版。
- 每天台北時間 23:00 由 Codex 自動抓候選、審稿、改寫並發 Discord，不需要再問主人確認。
- 23:20 自動補檢一次，如果當天沒有成功發送標記，就重新跑審稿與發送。
- 發送成功標記以 `data/game_news_sent.json` 為準；只有 Discord 全部 chunks 成功後才允許寫入。
- 如果 23:00 或 23:20 heartbeat 沒被處理，主人說「處理一下」時，補跑前一晚日報；若現在是台北 00:00-02:59，使用 `--sent-date` 標記前一天日期，避免錯算到今天。

## 目前狀態

- Repo：`https://github.com/karustestjp001-dotcom/game-news-discord-bot`
- Discord webhook：存在於本機使用者環境變數與 GitHub Secret `DISCORD_WEBHOOK_URL`，不要寫入檔案。
- Bilibili cookie：存在於 GitHub Secret `BILIBILI_COOKIE`，不要寫入檔案。
- 已確認成功發送日期目前記錄在 `data/game_news_sent.json`。
- GitHub Actions 的遊戲新聞排程已關閉，只保留手動 `workflow_dispatch`，避免 GitHub schedule 延遲亂發。

## 每晚 23:00 主流程

1. 在 repo 根目錄執行：

```powershell
$env:PYTHONUTF8="1"
python ".\scripts\game_news_report.py" --lookback-days 4 --top-per-category 8 --output ".\game_news_final_report.md" --source-output ".\game_news_source.md"
```

2. 讀 `game_news_source.md`，不要直接發規則版 `game_news_final_report.md`。
3. 由 Codex 重新寫 `game_news_final_report.md`：
   - 標題使用 `# 遊戲新聞貓娘雷達｜Codex 編輯版`
   - 繁體中文。
   - 可愛貓娘情報語氣，但不要模板廢話。
   - 只使用候選清單裡的新聞與連結。
   - 挑 8-15 則；品質差時可以少於 8 則。
   - 排除低價值列表文、純預告洗稿、來源弱且事件不明的條目。
   - 每則保留原文連結、熱度標記，並補 1-3 句「編輯判斷」。
   - 必須說清楚為什麼值得看，或為什麼需要觀望。
4. 發送 Discord：

```powershell
python ".\scripts\post_markdown_to_discord.py" ".\game_news_final_report.md" --title "遊戲新聞貓娘雷達" --sent-state ".\data\game_news_sent.json"
```

只有 Discord 全部 chunks 成功發送後，`post_markdown_to_discord.py` 才會寫入 `data/game_news_sent.json`。

## 20 分鐘補檢流程

補檢時先看 `data/game_news_sent.json`。如果台北日期今天已經在 `sent` 裡，直接停止。

如果現在是台北 00:00-02:59，補檢目標仍視為前一天晚上 23:00 的日報；可用 `--sent-date YYYY-MM-DD` 標記前一天日期。

如果目標日期尚未發送，就重新執行每晚主流程並發送。
