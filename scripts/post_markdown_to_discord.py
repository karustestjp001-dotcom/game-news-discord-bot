#!/usr/bin/env python3
"""Post an existing Markdown report to Discord with section-aware chunking."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def split_section(section: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in section.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0

        if line_len > limit:
            wrapped = textwrap.wrap(line, width=limit - 20) or [line]
            for wrapped_line in wrapped:
                if current:
                    chunks.append("\n".join(current).strip())
                    current = []
                    current_len = 0
                chunks.append(wrapped_line)
            continue

        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current).strip())
    return chunks


def chunk_markdown(markdown: str, limit: int = 1850) -> list[str]:
    sections: list[str] = []
    current: list[str] = []

    for line in markdown.splitlines():
        if line.startswith("## ") and current:
            sections.append("\n".join(current).strip())
            current = [line]
            continue
        current.append(line)

    if current:
        sections.append("\n".join(current).strip())

    chunks: list[str] = []
    current_chunk = ""
    for section in sections:
        for part in split_section(section, limit):
            separator = "\n\n" if current_chunk else ""
            if current_chunk and len(current_chunk) + len(separator) + len(part) > limit:
                chunks.append(current_chunk.strip())
                current_chunk = part
            else:
                current_chunk = f"{current_chunk}{separator}{part}"

    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


def post_json(
    webhook_url: str,
    content: str,
    *,
    thread_id: str | None = None,
    thread_name: str | None = None,
    wait: bool = False,
) -> dict | None:
    payload = {"content": content, "flags": 4}
    if thread_name:
        payload["thread_name"] = thread_name
    body = json.dumps(payload).encode("utf-8")
    params = {}
    if thread_id:
        params["thread_id"] = thread_id
    if wait:
        params["wait"] = "true"
    url = webhook_url
    if params:
        separator = "&" if "?" in webhook_url else "?"
        url = f"{webhook_url}{separator}{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "WorldMonitorNewsReporter/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            if raw:
                return json.loads(raw.decode("utf-8"))
            return None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord webhook failed: HTTP {exc.code}: {detail}") from exc


def taipei_today() -> str:
    taipei = dt.timezone(dt.timedelta(hours=8))
    return dt.datetime.now(taipei).strftime("%Y-%m-%d")


def mark_sent(path: str, title: str, sent_date: str | None = None) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        with state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    else:
        state = {}
    date_key = sent_date or taipei_today()
    sent = state.setdefault("sent", {})
    sent[date_key] = {
        "title": title,
        "sent_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
    }
    with state_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Post Markdown to Discord.")
    parser.add_argument("markdown_file")
    parser.add_argument("--title", default="World Monitor 重大新聞貓娘雷達")
    parser.add_argument("--webhook-env", default="DISCORD_WEBHOOK_URL")
    parser.add_argument("--thread-id", help="Existing Discord forum/thread id to post into.")
    parser.add_argument("--thread-name", help="Create a new forum thread with this name.")
    parser.add_argument("--sent-state", help="Write a sent marker JSON file after all Discord chunks succeed.")
    parser.add_argument("--sent-date", help="Date key to mark as sent, defaults to today's Taipei date.")
    args = parser.parse_args()

    webhook_url = os.environ.get(args.webhook_env)
    if not webhook_url:
        raise RuntimeError(f"Set {args.webhook_env} before posting.")

    with open(args.markdown_file, "r", encoding="utf-8") as handle:
        markdown = handle.read()

    chunks = chunk_markdown(markdown)
    total = len(chunks)
    thread_id = args.thread_id
    for index, chunk in enumerate(chunks, start=1):
        if total == 1:
            content = chunk
        else:
            content = f"**{args.title}（第 {index}/{total} 篇）**\n{chunk}"
        create_thread = bool(args.thread_name and not thread_id and index == 1)
        response = post_json(
            webhook_url,
            content,
            thread_id=thread_id,
            thread_name=args.thread_name if create_thread else None,
            wait=create_thread,
        )
        if create_thread and response:
            thread_id = str(response.get("channel_id") or "")

    if args.sent_state:
        mark_sent(args.sent_state, args.title, args.sent_date)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
