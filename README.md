# Game News Radar Workflow

這套流程用來自動抓取中西遊戲新聞，輸出繁中摘要與貓娘點評，並可透過 Discord webhook 轉發。

## 目標

- 中國手遊/二遊：版號、公測、測試招募、廠商與營運消息。
- Steam/PC 大作：發售、DLC、更新、延期、玩家評價與 Steam Deck 訊號。
- 高期待獨立遊戲：Demo、Next Fest、願望清單、募資與早期口碑。
- 主機/歐美日大作：Nintendo、PlayStation、Xbox、日廠與歐美大作節點。
- 產業警訊：停服、裁員、炎上、課金與營運爭議。

## 本機執行

```powershell
$env:PYTHONUTF8="1"
python ".\scripts\game_news_report.py" --lookback-days 4 --top-per-category 5 --output ".\game_news_final_report.md" --source-output ".\game_news_source.md"
```

若要發到 Discord：

```powershell
$env:DISCORD_WEBHOOK_URL="<discord webhook>"
python ".\scripts\post_markdown_to_discord.py" ".\game_news_final_report.md" --title "遊戲新聞貓娘雷達"
```

## GitHub Actions

`.github/workflows/game-news-radar.yml` 已設定每天台北時間約 23:00 自動跑一次，也可以手動 `workflow_dispatch`。

需要在 GitHub repo secrets 設定：

```text
DISCORD_WEBHOOK_URL
```

如果沒有設定 webhook，workflow 仍會產生 Markdown artifact，但不會發 Discord。

## 點評模式

目前是全自動規則點評：程式依來源、關鍵字、時效和分類產生熱度與重要度，再寫出繁中判讀。優點是穩定、便宜、可定時；缺點是它只讀 RSS 標題與來源，不會像 Codex 親自讀完候選新聞後那樣有細緻判斷。

若要半自動高品質版，流程是：

1. 先跑 `scripts/game_news_report.py` 產生 `game_news_source.md`。
2. Codex 讀候選清單與原文重點。
3. Codex 改寫 `game_news_final_report.md`，補上真正的取捨、上下文和個人化點評。
4. 再用 `scripts/post_markdown_to_discord.py` 發送。

## 後續可接 Cloudflare

如果之後想把排程搬到 Cloudflare，可以把抓取邏輯改成 Worker Cron Trigger，或讓 Cloudflare 只負責叫 GitHub Actions / Webhook。現在先用 GitHub Actions 是因為它對 Python 腳本和 artifact 最省事，不需要先改寫成 Worker。
