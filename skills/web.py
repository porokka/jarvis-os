"""
JARVIS Skill — Web search (DuckDuckGo) and URL opening.
"""

import os
import subprocess
import webbrowser
from typing import Optional
from urllib.parse import urlparse


SKILL_NAME = "web"
SKILL_DESCRIPTION = "Web search via DuckDuckGo + open URLs in browser"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "utility"
SKILL_TAGS = ["web", "search", "browser", "duckduckgo", "urls"]
SKILL_REQUIREMENTS = ["duckduckgo-search or ddgs package for search"]
SKILL_CAPABILITIES = [
    "web_search",
    "open_url",
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
    "entrypoint": "exec_web_search",
}


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _normalize_url(url: str) -> Optional[str]:
    url = (url or "").strip()
    if not url:
        return None

    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None

    return url


def exec_web_search(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return "Error: search query is required"

    try:
        # Newer package import
        try:
            from ddgs import DDGS
        except ImportError:
            # Older package import fallback
            from duckduckgo_search import DDGS

        results = DDGS().text(query, max_results=5)
        if not results:
            return "No results found."

        lines = []
        for r in results:
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            href = (r.get("href") or "").strip()

            line = f"- {title}"
            if href:
                line += f"\n  {href}"
            if body:
                line += f"\n  {body}"
            lines.append(line)

        return _truncate("\n".join(lines), 4000)

    except ImportError:
        return (
            "Error: DuckDuckGo search library not installed. "
            "Install one of: pip install ddgs  or  pip install duckduckgo-search"
        )
    except Exception as e:
        return f"Search error: {e}"


def exec_open_url(url: str) -> str:
    normalized = _normalize_url(url)
    if not normalized:
        return "Error: invalid or unsupported URL. Only http/https URLs are allowed."

    try:
        if os.name == "nt":
            subprocess.Popen(
                ["powershell.exe", "-Command", f"Start-Process '{normalized}'"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            webbrowser.open(normalized)

        return f"Opened {normalized}"
    except Exception as e:
        return f"Error opening URL: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information such as news, weather, prices, products, or general web results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open an http or https URL in the default browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to open"
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "web_search": exec_web_search,
    "open_url": exec_open_url,
}

KEYWORDS = {
    "web_search": [
        "search",
        "google",
        "find online",
        "weather",
        "news",
        "price",
        "where can i",
        "buy",
        "latest",
        "look up",
        "web search",
    ],
    "open_url": [
        "open",
        "browse",
        "website",
        "url",
        "open page",
        "open site",
    ],
}

SKILL_EXAMPLES = [
    {"command": "search latest nvidia news", "tool": "web_search", "args": {"query": "latest NVIDIA news"}},
    {"command": "search weather in Tallinn", "tool": "web_search", "args": {"query": "weather Tallinn"}},
    {"command": "open openai website", "tool": "open_url", "args": {"url": "https://openai.com"}},
]