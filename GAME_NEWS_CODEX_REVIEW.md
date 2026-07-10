# Codex 遊戲新聞審稿流程

這份流程給 Codex 自動化使用。Bilibili 影片不走這份流程，仍然由 GitHub Actions 無腦轉發。

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
