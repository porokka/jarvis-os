# Web Skill

Web search via DuckDuckGo and open URLs in the default browser.

**File:** `skills/web.py`

---

## Prerequisites

- **DuckDuckGo search:** `pip install duckduckgo-search`
- For URL opening: Windows with PowerShell

---

## Tools

### web_search

Search the web for current information.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Search query |

Returns top 5 results with title and snippet (max 4000 chars).

**Examples:**
```
"Search for latest Next.js 15 features"
"What's the weather in Helsinki?"
"Find best practices for React Server Components"
"Latest Bitcoin price"
```

---

### open_url

Open a URL in the default Windows browser.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | yes | URL to open |

**Examples:**
```
"Open GitHub"
"Open https://vercel.com/dashboard"
```
