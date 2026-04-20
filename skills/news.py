"""
JARVIS Skill — News by topic and optional location.

Uses Google News RSS feeds.
Supports:
- top headlines by location
- topic search with optional location boost

No API key required.
"""

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional


SKILL_NAME = "news"
SKILL_DESCRIPTION = "News headlines by topic and optional location"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "utility"
SKILL_TAGS = ["news", "headlines", "location", "topic", "rss"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "top_news",
    "search_news",
]

SKILL_META = {
    "name": SKILL_NAME,
    "description": SKILL_DESCRIPTION,
    "version": SKILL_VERSION,
    "author": SKILL_AUTHOR,
    "category": SKILL_CATEGORY,
    "tags": SKILL_TAGS,
    "requirements": SKILL_REQUIREMENTS,
    "capabilities": SKILL_CAPABILITIES,
    "writes_files": False,
    "reads_files": False,
    "network_access": True,
    "entrypoint": "exec_news",
}

GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search"
GOOGLE_NEWS_TOP = "https://news.google.com/rss"

LANG_BY_LOCATION = {
    "estonia": ("en-US", "US:en"),
    "tallinn": ("en-US", "US:en"),
    "finland": ("en-US", "US:en"),
    "helsinki": ("en-US", "US:en"),
    "sweden": ("en-US", "US:en"),
    "stockholm": ("en-US", "US:en"),
    "uk": ("en-GB", "GB:en"),
    "united kingdom": ("en-GB", "GB:en"),
    "london": ("en-GB", "GB:en"),
    "usa": ("en-US", "US:en"),
    "united states": ("en-US", "US:en"),
    "new york": ("en-US", "US:en"),
}


def _truncate(text: str, limit: int = 5000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def _clean_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _lang_region(location: str) -> tuple[str, str]:
    key = (location or "").strip().lower()
    if key in LANG_BY_LOCATION:
        return LANG_BY_LOCATION[key]
    return ("en-US", "US:en")


def _rss_fetch(url: str, timeout: int = 12) -> List[Dict[str, str]]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml_data = resp.read().decode("utf-8", errors="replace")

    root = ET.fromstring(xml_data)
    items = []

    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title", default=""))
        link = _clean_text(item.findtext("link", default=""))
        pub = _clean_text(item.findtext("pubDate", default=""))
        source = ""
        source_el = item.find("source")
        if source_el is not None and source_el.text:
            source = _clean_text(source_el.text)

        if title:
            items.append({
                "title": title,
                "link": link,
                "pubDate": pub,
                "source": source,
            })

    return items


def _format_items(title: str, items: List[Dict[str, str]], limit: int = 8) -> str:
    if not items:
        return f"{title}:\nNo news found."

    lines = [f"{title}:"]
    for item in items[:limit]:
        line = f"- {item.get('title', '')}"
        if item.get("source"):
            line += f" [{item['source']}]"
        if item.get("pubDate"):
            line += f"\n  {item['pubDate']}"
        if item.get("link"):
            line += f"\n  {item['link']}"
        lines.append(line)

    return "\n".join(lines)


def exec_news(action: str, topic: str = "", location: str = "", limit: int = 8) -> str:
    action = (action or "").strip().lower()
    topic = (topic or "").strip()
    location = (location or "").strip()
    limit = max(1, min(int(limit), 15))

    if action not in {"top", "search"}:
        return "Available actions: top, search"

    lang, ceid = _lang_region(location)

    try:
        if action == "top":
            if location:
                query = urllib.parse.urlencode({
                    "q": location,
                    "hl": lang,
                    "gl": lang.split("-")[-1],
                    "ceid": ceid,
                })
                url = f"{GOOGLE_NEWS_SEARCH}?{query}"
                items = _rss_fetch(url)
                return _truncate(_format_items(f"Top news for {location}", items, limit=limit), 5000)

            query = urllib.parse.urlencode({
                "hl": lang,
                "gl": lang.split("-")[-1],
                "ceid": ceid,
            })
            url = f"{GOOGLE_NEWS_TOP}?{query}"
            items = _rss_fetch(url)
            return _truncate(_format_items("Top news", items, limit=limit), 5000)

        if not topic:
            return "Error: topic is required for search."

        query_text = topic
        if location:
            query_text = f"{topic} {location}"

        query = urllib.parse.urlencode({
            "q": query_text,
            "hl": lang,
            "gl": lang.split("-")[-1],
            "ceid": ceid,
        })
        url = f"{GOOGLE_NEWS_SEARCH}?{query}"
        items = _rss_fetch(url)

        title = f"News for '{topic}'"
        if location:
            title += f" in {location}"

        return _truncate(_format_items(title, items, limit=limit), 5000)

    except Exception as e:
        return f"News error: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "news",
            "description": "Get live news headlines. Actions: top for general/location headlines, search for topic-based news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["top", "search"],
                        "description": "News action to perform.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic to search for, e.g. AI, NVIDIA, Ukraine",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional location, e.g. Tallinn, Estonia, London",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of headlines to return. Default 8.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "news": exec_news,
}

KEYWORDS = {
    "news": [
        "news",
        "headlines",
        "latest news",
        "what's happening",
        "top stories",
        "local news",
        "news in",
    ],
}

SKILL_EXAMPLES = [
    {"command": "top news in Estonia", "tool": "news", "args": {"action": "top", "location": "Estonia"}},
    {"command": "latest AI news", "tool": "news", "args": {"action": "search", "topic": "AI"}},
    {"command": "Ukraine news in Europe", "tool": "news", "args": {"action": "search", "topic": "Ukraine", "location": "Europe"}},
]