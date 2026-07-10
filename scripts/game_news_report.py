#!/usr/bin/env python3
"""Fetch game-news candidates and publish a Traditional Chinese radar report.

The script is dependency-free so it can run from GitHub Actions, a local
machine, or a small scheduled runner. It uses public Google News RSS searches
as the collection layer, then applies transparent scoring and lightweight
editorial judgment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any


DEFAULT_USER_AGENT = "GameNewsRadar/1.0"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"


SOURCE_WEIGHTS = {
    "Steam": 18,
    "SteamDB": 17,
    "Gematsu": 17,
    "IGN": 16,
    "PC Gamer": 16,
    "Eurogamer": 15,
    "VGC": 15,
    "GameSpot": 14,
    "Polygon": 14,
    "The Verge": 13,
    "Rock Paper Shotgun": 13,
    "Automaton": 13,
    "4Gamer": 13,
    "Famitsu": 13,
    "GameLook": 16,
    "遊戲葡萄": 15,
    "手游那點事": 15,
    "TapTap": 14,
    "機核": 13,
    "遊民星空": 13,
    "3DMGAME": 12,
    "17173": 12,
    "巴哈姆特": 12,
    "Yahoo奇摩遊戲": 11,
}


CATEGORY_PROFILES: dict[str, dict[str, Any]] = {
    "中國手遊/二遊": {
        "min_keyword_score": 8,
        "queries": [
            ("中國 手遊 公測 版號 新作", "zh-TW", "TW"),
            ("手遊 新作 公測 測試", "zh-TW", "TW"),
            ("騰訊 網易 米哈遊 鷹角 莉莉絲 手遊", "zh-TW", "TW"),
            ("巴哈姆特 手機遊戲 公測 事前登錄", "zh-TW", "TW"),
            ("TapTap 手游 测试 招募 公测", "zh-CN", "CN"),
            ("手游 新游 公测 测试", "zh-CN", "CN"),
            ("二次元 手游 新作 公测", "zh-CN", "CN"),
            ("GameLook 手游 新游 二次元", "zh-CN", "CN"),
        ],
        "keywords": {
            "手遊": 12,
            "手游": 12,
            "二遊": 10,
            "二次元": 10,
            "公測": 11,
            "公测": 11,
            "測試": 8,
            "测试": 8,
            "版號": 12,
            "版号": 12,
            "騰訊": 8,
            "腾讯": 8,
            "網易": 8,
            "网易": 8,
            "米哈遊": 8,
            "米哈游": 8,
            "TapTap": 7,
            "流水": 8,
            "抽卡": 6,
            "事前登錄": 7,
            "预约": 7,
        },
    },
    "Steam 大作/PC 遊戲": {
        "min_keyword_score": 8,
        "queries": [
            ("Steam major game release DLC update PC Gamer IGN", "en-US", "US"),
            ("PC game release date Steam trailer review", "en-US", "US"),
            ("Steam top seller new release review PC game", "en-US", "US"),
            ("Steam 新作 大作 發售 評價", "zh-TW", "TW"),
            ("Steam 新作 發售 DLC 更新", "zh-TW", "TW"),
            ("Steam Deck verified major game update", "en-US", "US"),
        ],
        "keywords": {
            "Steam": 13,
            "PC": 6,
            "release": 9,
            "launch": 8,
            "DLC": 8,
            "update": 7,
            "review": 6,
            "delayed": 9,
            "wishlist": 7,
            "demo": 6,
            "發售": 10,
            "上市": 8,
            "更新": 6,
            "大作": 10,
            "特價": 5,
        },
    },
    "高期待獨立遊戲": {
        "min_keyword_score": 8,
        "queries": [
            ("Steam Next Fest indie game demo release wishlist", "en-US", "US"),
            ("indie game Steam demo release highly anticipated", "en-US", "US"),
            ("new indie game Steam release demo", "en-US", "US"),
            ("獨立遊戲 Steam demo 發售 期待", "zh-TW", "TW"),
            ("獨立遊戲 試玩 發售 Steam", "zh-TW", "TW"),
            ("Wholesome Direct indie game Steam release", "en-US", "US"),
        ],
        "keywords": {
            "indie": 13,
            "independent": 9,
            "Next Fest": 12,
            "demo": 10,
            "wishlist": 11,
            "Kickstarter": 8,
            "early access": 9,
            "cozy": 5,
            "roguelike": 5,
            "metroidvania": 6,
            "獨立": 13,
            "試玩": 8,
            "願望清單": 11,
            "募資": 7,
        },
    },
    "主機/歐美日大作": {
        "min_keyword_score": 8,
        "queries": [
            ("PlayStation Xbox Nintendo game release trailer delayed", "en-US", "US"),
            ("Nintendo Direct PlayStation State of Play Xbox showcase game", "en-US", "US"),
            ("JRPG action RPG release date trailer Gematsu Famitsu", "en-US", "US"),
            ("video game release date trailer delayed Gematsu IGN", "en-US", "US"),
            ("任天堂 PlayStation Xbox 新作 發售 延期", "zh-TW", "TW"),
        ],
        "keywords": {
            "PlayStation": 10,
            "PS5": 10,
            "Xbox": 10,
            "Nintendo": 10,
            "Switch": 10,
            "Direct": 7,
            "trailer": 8,
            "showcase": 7,
            "release date": 9,
            "delayed": 10,
            "JRPG": 7,
            "任天堂": 10,
            "延期": 10,
            "發表": 7,
        },
    },
    "營運/產業警訊": {
        "min_keyword_score": 8,
        "queries": [
            ("game layoffs studio closure live service shutdown", "en-US", "US"),
            ("game review bombing controversy monetization gacha", "en-US", "US"),
            ("game server shutdown controversy update players", "en-US", "US"),
            ("遊戲 停服 炎上 課金 爭議 工作室 裁員", "zh-TW", "TW"),
            ("游戏 停服 炎上 付费 争议 裁员", "zh-CN", "CN"),
        ],
        "keywords": {
            "layoffs": 14,
            "closure": 12,
            "shutdown": 12,
            "cancelled": 10,
            "controversy": 11,
            "review bombing": 13,
            "monetization": 9,
            "gacha": 8,
            "停服": 13,
            "炎上": 12,
            "爭議": 11,
            "争议": 11,
            "課金": 8,
            "裁員": 13,
            "裁员": 13,
        },
    },
}


@dataclass
class Article:
    title: str
    url: str
    source: str
    category: str
    published: dt.datetime | None = None
    keyword_score: float = 0
    source_score: float = 0
    heat: float = 0
    importance: int = 0
    level: str = "LOW"
    matched_keywords: list[str] = field(default_factory=list)
    summary: str = ""


def now_taipei() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone(dt.timedelta(hours=8)))


def google_rss_url(query: str, language: str, region: str, lookback_days: int) -> str:
    dated_query = f"{query} when:{lookback_days}d"
    params = {
        "q": dated_query,
        "hl": language,
        "gl": region,
        "ceid": f"{region}:{language.split('-')[0]}",
    }
    return f"{GOOGLE_NEWS_RSS_URL}?{urllib.parse.urlencode(params)}"


def fetch_url(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def infer_source(item: ET.Element, title: str) -> str:
    source = item.findtext("source")
    if source:
        return clean_text(source)
    match = re.search(r" - ([^-]+)$", title)
    if match:
        return clean_text(match.group(1))
    return "Google News"


def source_weight(source: str) -> float:
    for name, weight in SOURCE_WEIGHTS.items():
        if name.lower() in source.lower():
            return weight
    return 8


def keyword_score(text: str, keywords: dict[str, int]) -> tuple[float, list[str]]:
    lowered = text.lower()
    score = 0.0
    matched: list[str] = []
    for keyword, weight in keywords.items():
        if keyword.lower() in lowered:
            score += weight
            matched.append(keyword)
    return score, matched


def recency_score(published: dt.datetime | None, reference: dt.datetime) -> float:
    if not published:
        return 0
    hours = max((reference - published).total_seconds() / 3600, 0)
    return max(0, 24 - hours) * 0.55


def classify_heat(heat: float) -> str:
    if heat >= 130:
        return "CRITICAL"
    if heat >= 100:
        return "HIGH"
    if heat >= 70:
        return "MEDIUM"
    return "LOW"


def heat_icon(heat: float) -> str:
    if heat >= 130:
        return "🔴"
    if heat >= 100:
        return "🟠"
    if heat >= 70:
        return "🟡"
    return "⚪"


def importance_icon(importance: int) -> str:
    if importance >= 90:
        return "🔴"
    if importance >= 70:
        return "🟠"
    if importance >= 50:
        return "🟡"
    return "⚪"


def normalize_title(title: str) -> str:
    normalized = re.sub(r"\s+-\s+[^-]+$", "", title)
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized.lower())
    return normalized[:90]


def fetch_category_articles(
    category: str,
    profile: dict[str, Any],
    lookback_days: int,
    reference: dt.datetime,
) -> list[Article]:
    articles: list[Article] = []
    min_time = reference - dt.timedelta(days=lookback_days)
    for query, language, region in profile["queries"]:
        url = google_rss_url(query, language, region, lookback_days)
        try:
            raw = fetch_url(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"[warn] failed to fetch {category}: {query}: {exc}", file=sys.stderr)
            continue

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            print(f"[warn] failed to parse RSS {category}: {query}: {exc}", file=sys.stderr)
            continue

        for item in root.findall("./channel/item"):
            title = clean_text(item.findtext("title"))
            link = clean_text(item.findtext("link"))
            published = parse_datetime(item.findtext("pubDate"))
            if not title or not link:
                continue
            if published and published < min_time:
                continue
            source = infer_source(item, title)
            summary = clean_text(item.findtext("description"))
            combined = f"{title} {source} {summary}"
            score, matched = keyword_score(combined, profile["keywords"])
            if score < profile["min_keyword_score"]:
                continue
            article = Article(
                title=title,
                url=link,
                source=source,
                category=category,
                published=published,
                keyword_score=score,
                source_score=source_weight(source),
                matched_keywords=matched,
                summary=summary,
            )
            recency = recency_score(published, reference)
            article.heat = round(score * 3.6 + article.source_score * 2.3 + recency, 1)
            article.importance = min(100, max(1, round(math.sqrt(article.heat) * 8.7)))
            article.level = classify_heat(article.heat)
            articles.append(article)
    return articles


def dedupe_articles(articles: list[Article]) -> list[Article]:
    best_by_title: dict[str, Article] = {}
    for article in articles:
        key = normalize_title(article.title)
        current = best_by_title.get(key)
        if not current or article.heat > current.heat:
            best_by_title[key] = article
    return sorted(best_by_title.values(), key=lambda item: item.heat, reverse=True)


def fetch_all_articles(lookback_days: int, top_per_category: int) -> dict[str, list[Article]]:
    reference = now_taipei()
    result: dict[str, list[Article]] = {}
    for category, profile in CATEGORY_PROFILES.items():
        articles = fetch_category_articles(category, profile, lookback_days, reference)
        result[category] = dedupe_articles(articles)[:top_per_category]
    return result


def format_time(published: dt.datetime | None) -> str:
    if not published:
        return "時間未標"
    return published.strftime("%Y-%m-%d %H:%M")


def article_line(article: Article) -> str:
    return (
        f"[{article.title}]({article.url})\n"
        f"熱度標記：{article.source} | 熱度 {heat_icon(article.heat)} {article.heat:.1f} | "
        f"重要度 {importance_icon(article.importance)} {article.importance} | "
        f"{article.level}/{article.category} | {format_time(article.published)}"
    )


def category_commentary(category: str, articles: list[Article]) -> str:
    if not articles:
        return ""
    top = articles[0]
    keywords = sorted({keyword for article in articles for keyword in article.matched_keywords})
    keyword_text = "、".join(keywords[:6]) if keywords else "熱度與來源密度"
    count = len(articles)
    if category == "中國手遊/二遊":
        return (
            f"這一欄目前有 {count} 則值得看，重心落在「{keyword_text}」。"
            f"最高熱度是 {top.source} 的消息，代表中國手遊圈現在更像是測試、版號、上線節奏在拉動注意力。"
            "若同一款作品連續幾天出現，通常就值得獨立追蹤社群口碑和商業化反應喵。"
        )
    if category == "Steam 大作/PC 遊戲":
        return (
            f"Steam/PC 這邊有 {count} 則訊號，關鍵字集中在「{keyword_text}」。"
            f"{top.source} 的最高分條目先放前面，因為它比較可能影響願望清單、首週銷量或玩家回鍋。"
            "我會優先看發售日、評價變化、DLC 內容和 Steam Deck 相容性，這些最容易改變玩家要不要立刻買喵。"
        )
    if category == "高期待獨立遊戲":
        return (
            f"獨立遊戲欄抓到 {count} 則，主要看「{keyword_text}」。"
            "這類新聞不能只看聲量，Demo、願望清單、Next Fest 曝光和實況圈帶動才是比較可靠的早期指標。"
            f"目前最高分來自 {top.source}，可以先當作今晚的觀察樣本喵。"
        )
    if category == "主機/歐美日大作":
        return (
            f"主機與大作線有 {count} 則，訊號集中在「{keyword_text}」。"
            "這裡的價值是幫 Steam 視角補上平台獨佔、展示會與日廠新作，不然很容易漏掉真正的大型節點。"
            f"最高熱度的 {top.source} 條目適合優先確認是否有發售日、延期或新預告喵。"
        )
    return (
        f"產業警訊抓到 {count} 則，關鍵字是「{keyword_text}」。"
        "這類消息我會比較保守處理，因為裁員、停服、炎上和課金爭議常常需要第二來源交叉確認。"
        f"目前最高分來自 {top.source}，適合當作後續追蹤起點，而不是直接下定論喵。"
    )


def generate_report(categorized: dict[str, list[Article]], *, source_note: str) -> str:
    generated = now_taipei().strftime("%Y-%m-%d %H:%M")
    populated = {category: items for category, items in categorized.items() if items}
    total = sum(len(items) for items in populated.values())
    lines: list[str] = [
        "# 遊戲新聞貓娘雷達｜中西情報自動版",
        f"生成時間：{generated} 台北時間",
        "",
        "## 分數說明",
        "- 熱度：本機規則初評，🟡 70-99 算高，🟠 100-129 算很高，🔴 130 以上算重點警訊喵。",
        "- 重要度：由本機規則熱度換算的 1-100 輔助分數；🟡 50-69 列入觀察，🟠 70-89 算高，🔴 90 以上算非常高喵。",
        f"- 資料來源：{source_note}。這是自動化摘要，不全文轉載，請以原文連結為準。",
        "",
        "## 總覽",
    ]
    if not total:
        lines.append("這輪沒有抓到足夠高訊號的遊戲新聞，先不硬湊內容喵。")
        return "\n".join(lines).strip() + "\n"

    category_names = "、".join(populated.keys())
    lines.append(
        f"本輪共挑出 {total} 則候選新聞，覆蓋 {category_names}。"
        "我會把中國手遊、Steam/PC 大作、高期待獨立遊戲和產業警訊放在同一張雷達上，避免只看單一語圈造成偏食。"
        "自動點評偏向先抓趨勢和追蹤價值，真正要轉推時仍建議看原文標題與來源喵。"
    )
    lines.append("")

    for category, articles in populated.items():
        lines.append(f"## {category}")
        lines.append(category_commentary(category, articles))
        lines.append("")
        for article in articles:
            lines.append(article_line(article))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def generate_source_dump(categorized: dict[str, list[Article]]) -> str:
    generated = now_taipei().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 遊戲新聞來源候選清單",
        f"生成時間：{generated} 台北時間",
        "",
        "這份檔案保留自動抓取與初評結果，給人工/Codex 二次點評時使用喵。",
        "",
    ]
    for category, articles in categorized.items():
        lines.append(f"## {category}")
        if not articles:
            lines.append("本輪沒有達標候選。")
            lines.append("")
            continue
        for article in articles:
            matched = "、".join(article.matched_keywords) or "無"
            lines.append(article_line(article))
            lines.append(f"命中關鍵字：{matched}")
            if article.summary:
                lines.append(f"RSS 摘要：{article.summary}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()

    parts: list[str] = []
    for output in payload.get("output", []) or []:
        for content in output.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def generate_ai_editor_report(
    source_dump: str,
    *,
    model: str,
    api_key: str,
    timeout: int = 90,
) -> str:
    generated = now_taipei().strftime("%Y-%m-%d %H:%M")
    system_prompt = (
        "你是遊戲新聞 AI 編輯。你要從候選清單中挑真正值得玩家知道的新聞，"
        "寫成繁體中文 Discord 日報。語氣可愛、有貓娘感，但判斷要像嚴格編輯，"
        "不要照單全收，不要寫空泛模板，不要發明候選清單沒有的事實。"
    )
    user_prompt = f"""
請把下面的遊戲新聞候選清單改寫成「AI 編輯版」日報。

硬性規則：
- 只使用候選清單中的新聞與連結，不要新增外部新聞。
- 優先挑 8-15 則；如果候選品質差，可以少於 8 則，並在總覽說明。
- 分類保留：中國手遊/二遊、Steam 大作/PC 遊戲、高期待獨立遊戲、主機/歐美日大作、營運/產業警訊。
- 每則新聞要有一段 1-3 句短評，說清楚「為什麼值得看」或「為什麼先觀望」。
- 排除看起來像低價值列表文、純影片預告洗稿、來源弱且沒有明確事件的新聞。
- 不全文轉載，不要大段引用原文。
- 不要使用 Markdown 表格。
- 不要包 code fence。
- 直接輸出最終 Markdown。

建議結構：
# 遊戲新聞貓娘雷達｜AI 編輯版
生成時間：{generated} 台北時間

## 今日判斷
用 3-5 句說今天遊戲圈真正值得看的方向。

## 精選新聞
依分類分段，每則格式：
[標題](連結)
編輯判斷：...
熱度標記：...

## 觀望/剔除邏輯
用 2-4 句說哪些類型被降權，讓讀者知道不是無腦搬運。

候選清單如下：

{source_dump}
""".strip()
    body = json.dumps(
        {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": 3600,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": DEFAULT_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API failed: HTTP {exc.code}: {detail}") from exc

    text = extract_response_text(payload)
    if not text:
        raise RuntimeError("OpenAI API returned no output text.")
    return text.strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a game-news radar report.")
    parser.add_argument("--lookback-days", type=int, default=2)
    parser.add_argument("--top-per-category", type=int, default=5)
    parser.add_argument("--output", default="game_news_final_report.md")
    parser.add_argument("--source-output", default="game_news_source.md")
    parser.add_argument("--ai-editor", action="store_true")
    parser.add_argument("--require-ai", action="store_true")
    parser.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--openai-key-env", default="OPENAI_API_KEY")
    args = parser.parse_args()

    categorized = fetch_all_articles(args.lookback_days, args.top_per_category)
    source_dump = generate_source_dump(categorized)
    api_key = os.environ.get(args.openai_key_env, "")
    if args.ai_editor and api_key:
        report = generate_ai_editor_report(source_dump, model=args.openai_model, api_key=api_key)
    elif args.ai_editor and args.require_ai:
        raise RuntimeError(f"Set {args.openai_key_env} to generate the required AI editor report.")
    else:
        report = generate_report(categorized, source_note="Google News RSS 多語系搜尋")

    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(report)
    with open(args.source_output, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source_dump)

    selected = sum(len(items) for items in categorized.values())
    print(f"Wrote {args.output} and {args.source_output} with {selected} selected articles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
