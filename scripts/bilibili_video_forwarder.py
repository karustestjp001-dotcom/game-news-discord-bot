#!/usr/bin/env python3
"""Forward new Bilibili videos from configured channels to Discord.

State is stored in a JSON file so scheduled GitHub Actions runs only post each
video once. The first successful run for a channel creates a baseline and does
not post older videos.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CHANNELS = {
    "1265652806": "明日方舟终末地",
    "161775300": "明日方舟",
    "3546983822264909": "终末地Delta机器人",
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

TAIPEI = dt.timezone(dt.timedelta(hours=8))


@dataclass(frozen=True)
class Video:
    mid: str
    author: str
    bvid: str
    title: str
    url: str
    pub_ts: int
    description: str = ""


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def taipei_time(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, TAIPEI).strftime("%Y-%m-%d %H:%M")


def headers(mid: str, cookie: str | None = None) -> dict[str, str]:
    result = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": f"https://space.bilibili.com/{mid}/video",
        "Origin": "https://space.bilibili.com",
    }
    if cookie:
        result["Cookie"] = cookie
    return result


def fetch_text(url: str, mid: str, cookie: str | None = None, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers=headers(mid, cookie))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def video_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"


def parse_arc_search(mid: str, author: str, payload: dict[str, Any]) -> list[Video]:
    videos: list[Video] = []
    for item in payload.get("data", {}).get("list", {}).get("vlist", []) or []:
        bvid = clean_text(item.get("bvid"))
        if not bvid:
            continue
        videos.append(
            Video(
                mid=mid,
                author=clean_text(item.get("author")) or author,
                bvid=bvid,
                title=clean_text(item.get("title")) or bvid,
                url=video_url(bvid),
                pub_ts=int(item.get("created") or item.get("pubdate") or 0),
                description=clean_text(item.get("description")),
            )
        )
    return videos


def parse_dynamic_feed(mid: str, author: str, payload: dict[str, Any]) -> list[Video]:
    videos: list[Video] = []
    for item in payload.get("data", {}).get("items", []) or []:
        modules = item.get("modules", {}) or {}
        module_author = modules.get("module_author", {}) or {}
        item_author = clean_text(module_author.get("name")) or author
        pub_ts = int(module_author.get("pub_ts") or 0)
        major = (modules.get("module_dynamic", {}) or {}).get("major", {}) or {}
        archive = major.get("archive", {}) or {}
        bvid = clean_text(archive.get("bvid"))
        if not bvid:
            continue
        videos.append(
            Video(
                mid=mid,
                author=item_author,
                bvid=bvid,
                title=clean_text(archive.get("title")) or bvid,
                url=video_url(bvid),
                pub_ts=pub_ts,
                description=clean_text(archive.get("desc")),
            )
        )
    return videos


def parse_rss(mid: str, author: str, xml_text: str) -> list[Video]:
    root = ET.fromstring(xml_text)
    videos: list[Video] = []
    for item in root.findall("./channel/item"):
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        guid = clean_text(item.findtext("guid"))
        raw_id = link or guid
        match = re.search(r"(BV[0-9A-Za-z]+)", raw_id)
        if not match:
            continue
        published = item.findtext("pubDate")
        pub_ts = 0
        if published:
            try:
                pub_ts = int(email.utils.parsedate_to_datetime(published).timestamp())
            except (TypeError, ValueError):
                pub_ts = 0
        videos.append(
            Video(
                mid=mid,
                author=author,
                bvid=match.group(1),
                title=title or match.group(1),
                url=video_url(match.group(1)),
                pub_ts=pub_ts,
                description=clean_text(item.findtext("description")),
            )
        )
    return videos


def fetch_channel_videos(
    mid: str,
    author: str,
    *,
    cookie: str | None,
    rss_bases: list[str],
    page_size: int,
) -> list[Video]:
    errors: list[str] = []
    direct_urls = [
        (
            "arc",
            "https://api.bilibili.com/x/space/arc/search?"
            + urllib.parse.urlencode({"mid": mid, "ps": page_size, "pn": 1, "order": "pubdate"}),
        ),
        (
            "dynamic",
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?"
            + urllib.parse.urlencode(
                {"host_mid": mid, "timezone_offset": -480, "features": "itemOpusStyle"}
            ),
        ),
    ]

    for kind, url in direct_urls:
        try:
            payload = json.loads(fetch_text(url, mid, cookie))
            if int(payload.get("code", -1)) != 0:
                errors.append(f"{kind}: code {payload.get('code')} {payload.get('message')}")
                continue
            videos = parse_arc_search(mid, author, payload) if kind == "arc" else parse_dynamic_feed(mid, author, payload)
            if videos:
                return sorted(videos, key=lambda video: video.pub_ts, reverse=True)
            errors.append(f"{kind}: no videos")
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            errors.append(f"{kind}: {exc}")

    for base in rss_bases:
        url = f"{base.rstrip('/')}/bilibili/user/video/{mid}"
        try:
            videos = parse_rss(mid, author, fetch_text(url, mid, cookie))
            if videos:
                return sorted(videos, key=lambda video: video.pub_ts, reverse=True)
            errors.append(f"rss {base}: no videos")
        except (OSError, urllib.error.URLError, ET.ParseError) as exc:
            errors.append(f"rss {base}: {exc}")

    raise RuntimeError(f"Unable to fetch Bilibili channel {mid}: {'; '.join(errors)}")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"channels": {}}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("channels", {})
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = dt.datetime.now(TAIPEI).isoformat()
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def parse_channels(raw: str | None) -> dict[str, str]:
    if not raw:
        return dict(DEFAULT_CHANNELS)
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            mid, name = entry.split("=", 1)
            result[mid.strip()] = name.strip() or mid.strip()
        else:
            result[entry] = f"Bilibili {entry}"
    return result


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def discord_message(video: Video) -> str:
    lines = [
        f"**B站新影片｜{video.author}**",
        f"**{video.title}**",
        f"發布時間：{taipei_time(video.pub_ts)} 台北時間",
    ]
    if video.description:
        lines.append(truncate(video.description, 180))
    lines.append(video.url)
    return "\n".join(lines)


def post_to_discord(webhook_url: str, content: str, *, suppress_embeds: bool) -> None:
    payload: dict[str, Any] = {"content": content}
    if suppress_embeds:
        payload["flags"] = 4
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "BilibiliVideoForwarder/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def select_new_videos(
    mid: str,
    videos: list[Video],
    state: dict[str, Any],
    *,
    post_on_first_run: bool,
) -> tuple[list[Video], bool]:
    channels = state.setdefault("channels", {})
    channel_state = channels.get(mid)
    if channel_state is None:
        channels[mid] = {
            "seen_bvids": [video.bvid for video in videos[:50]],
            "latest_pub_ts": max((video.pub_ts for video in videos), default=0),
            "initialized_at": dt.datetime.now(TAIPEI).isoformat(),
        }
        return (videos if post_on_first_run else []), True

    seen = set(channel_state.get("seen_bvids", []))
    latest_pub_ts = int(channel_state.get("latest_pub_ts") or 0)
    new_videos = [
        video
        for video in videos
        if video.bvid not in seen and (not latest_pub_ts or video.pub_ts >= latest_pub_ts)
    ]
    if not new_videos:
        return [], False

    merged_seen = list(dict.fromkeys([video.bvid for video in videos] + list(seen)))[:200]
    channel_state["seen_bvids"] = merged_seen
    channel_state["latest_pub_ts"] = max(latest_pub_ts, max(video.pub_ts for video in videos))
    channel_state["last_posted_at"] = dt.datetime.now(TAIPEI).isoformat()
    return sorted(new_videos, key=lambda video: video.pub_ts), True


def main() -> int:
    parser = argparse.ArgumentParser(description="Forward new Bilibili videos to Discord.")
    parser.add_argument("--state-file", default="data/bilibili_state.json")
    parser.add_argument("--channels", default=os.environ.get("BILIBILI_CHANNELS"))
    parser.add_argument("--webhook-env", default="DISCORD_WEBHOOK_URL")
    parser.add_argument("--cookie-env", default="BILIBILI_COOKIE")
    parser.add_argument(
        "--rss-bases",
        default=os.environ.get(
            "BILIBILI_RSS_BASES",
            "https://rsshub.app,https://rsshub.rssforever.com",
        ),
    )
    parser.add_argument("--page-size", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--post-on-first-run", action="store_true")
    parser.add_argument("--suppress-embeds", action="store_true")
    args = parser.parse_args()

    channels = parse_channels(args.channels)
    webhook_url = os.environ.get(args.webhook_env, "")
    cookie = os.environ.get(args.cookie_env) or None
    rss_bases = [base.strip() for base in args.rss_bases.split(",") if base.strip()]
    state_path = Path(args.state_file)
    state = load_state(state_path)

    any_state_changed = False
    total_new = 0
    for index, (mid, author) in enumerate(channels.items()):
        if index:
            time.sleep(2)
        videos = fetch_channel_videos(
            mid,
            author,
            cookie=cookie,
            rss_bases=rss_bases,
            page_size=args.page_size,
        )
        new_videos, changed = select_new_videos(
            mid,
            videos,
            state,
            post_on_first_run=args.post_on_first_run,
        )
        any_state_changed = any_state_changed or changed
        for video in new_videos:
            total_new += 1
            message = discord_message(video)
            if args.dry_run or not webhook_url:
                print(message)
                print()
                continue
            post_to_discord(webhook_url, message, suppress_embeds=args.suppress_embeds)
            time.sleep(1)

    if any_state_changed:
        save_state(state_path, state)

    print(f"Checked {len(channels)} Bilibili channels, forwarded {total_new} new videos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
