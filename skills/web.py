"""
JARVIS Skill — Web search (DuckDuckGo) and URL opening.
"""

import subprocess

SKILL_NAME = "web"
SKILL_DESCRIPTION = "Web search via DuckDuckGo + open URLs in browser"


def exec_web_search(query: str) -> str:
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=5)
        if not results:
            return "No results found."
        lines = [f"- {r.get('title', '')}: {r.get('body', '')}" for r in results]
        return "\n".join(lines)[:4000]
    except ImportError:
        return "Error: duckduckgo-search not installed. Run: pip install duckduckgo-search"
    except Exception as e:
        return f"Search error: {e}"


def exec_open_url(url: str) -> str:
    try:
        subprocess.Popen(
            ["powershell.exe", "-Command", f"Start-Process '{url}'"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return f"Opened {url}"
    except Exception as e:
        return f"Error opening URL: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information. News, weather, prices, anything not in the vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open a URL in the default Windows browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to open"}
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_MAP = {
    "web_search": exec_web_search,
    "open_url": exec_open_url,
}

KEYWORDS = {
    "web_search": ["search", "google", "find online", "weather", "news", "price", "where can i", "buy", "latest"],
    "open_url": ["open", "browse", "website", "url"],
}
