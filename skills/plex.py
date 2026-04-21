"""
JARVIS Skill — Plex Media Server control.

Controls Plex via HTTP API. Requires a Plex token.
Config: config/plex.json

Setup:
  1. Get your Plex token: https://support.plex.tv/articles/204059436
  2. Create config/plex.json:
     {
       "ip": "192.168.1.100",
       "port": 32400,
       "token": "YOUR_TOKEN",
       "default_client": "Living Room Shield"
     }

Memory model:
  - This skill can scan Plex libraries and store media metadata locally
    into config/plex_memory.json.
  - JARVIS can then resolve titles from memory before playback.
"""

import json
import os
import re
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET


SKILL_NAME = "plex"
SKILL_DESCRIPTION = "Plex Media Server — browse, scan memory, search, play, and control playback"
SKILL_VERSION = "1.2.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "media"
SKILL_TAGS = ["plex", "media", "movies", "tv", "streaming", "library", "memory"]
SKILL_REQUIREMENTS = ["config/plex.json", "Plex token"]
SKILL_CAPABILITIES = [
    "server_status",
    "list_libraries",
    "search_live",
    "scan_to_memory",
    "search_memory",
    "list_clients",
    "play_media",
    "playback_control",
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
    "writes_files": True,
    "reads_files": True,
    "network_access": True,
    "entrypoint": "exec_plex",
    "config_file": "config/plex.json",
    "memory_file": "config/plex_memory.json",
}

CONFIG_FILE = Path(__file__).parent.parent / "config" / "plex.json"
MEMORY_FILE = Path(__file__).parent.parent / "config" / "plex_memory.json"


def _load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_memory() -> dict:
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"items": []}
    except Exception:
        return {"items": []}


def _save_memory(data: dict) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _validate_config(cfg: dict) -> Optional[str]:
    ip = str(cfg.get("ip", "")).strip()
    token = str(cfg.get("token", "")).strip()
    port = cfg.get("port", 32400)

    if not ip:
        return "Error: Plex not configured. Missing 'ip' in config/plex.json"
    if not token:
        return "Error: Plex not configured. Missing 'token' in config/plex.json"
    try:
        int(port)
    except Exception:
        return "Error: Plex config invalid. 'port' must be an integer."
    return None


def _base_url() -> str:
    cfg = _load_config()
    ip = str(cfg.get("ip", "")).strip()
    port = int(cfg.get("port", 32400))
    return f"http://{ip}:{port}"


def _token() -> str:
    cfg = _load_config()
    return str(cfg.get("token", "")).strip()


def _headers(extra: Optional[dict] = None) -> dict:
    hdrs = {
        "Accept": "application/xml",
        "X-Plex-Token": _token(),
        "X-Plex-Client-Identifier": "jarvis-plex-skill",
        "X-Plex-Product": "JARVIS",
        "X-Plex-Version": SKILL_VERSION,
        "X-Plex-Device-Name": "JARVIS",
        "X-Plex-Platform": os.name,
    }
    if extra:
        hdrs.update(extra)
    return hdrs


def _api(path: str, method: str = "GET", data: Optional[dict] = None) -> str:
    """Call Plex API and return raw text."""
    cfg = _load_config()
    err = _validate_config(cfg)
    if err:
        return err

    url = f"{_base_url()}{path}"
    if "X-Plex-Token=" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}X-Plex-Token={urllib.parse.quote(_token())}"

    encoded = None
    if data:
        encoded = urllib.parse.urlencode(data).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=encoded, method=method.upper())
        for k, v in _headers().items():
            req.add_header(k, v)

        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace")

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            body = str(e)
        return f"Error: Plex API {e.code}: {body}"

    except urllib.error.URLError as e:
        return f"Error: Cannot reach Plex server: {e}"

    except Exception as e:
        return f"Error: {e}"


def _xml_root(text: str) -> Optional[ET.Element]:
    if not text or text.startswith("Error:"):
        return None
    try:
        return ET.fromstring(text)
    except Exception:
        return None


def _attr(elem: ET.Element, name: str, default: str = "") -> str:
    return str(elem.attrib.get(name, default))


def _iter_videos(root: Optional[ET.Element]) -> List[ET.Element]:
    if root is None:
        return []
    out = []
    for tag in ("Video", "Directory"):
        out.extend(root.findall(f".//{tag}"))
    return out


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _score_match(title: str, query: str, year: str = "") -> int:
    t = _normalize(title)
    q = _normalize(query)

    if not q:
        return 0
    if t == q:
        return 100
    if t.startswith(q):
        return 90
    if q in t:
        return 75

    # crude token overlap
    tset = set(t.split())
    qset = set(q.split())
    overlap = len(tset & qset)
    if overlap:
        return min(70, overlap * 20)

    if year and year in query:
        return 5

    return 0


def _server_machine_id() -> str:
    text = _api("/")
    root = _xml_root(text)
    if root is None:
        return ""
    return _attr(root, "machineIdentifier")


def _list_libraries_data() -> List[dict]:
    result = _api("/library/sections")
    root = _xml_root(result)
    if root is None:
        return []

    libs = []
    for d in root.findall(".//Directory"):
        libs.append({
            "key": _attr(d, "key"),
            "title": _attr(d, "title"),
            "type": _attr(d, "type"),
        })
    return libs


def _scan_library_section(section_key: str, section_title: str, section_type: str) -> List[dict]:
    """
    Scan one library section.
    For movies, this is usually enough.
    For TV, this stores top-level show entries.
    """
    result = _api(f"/library/sections/{section_key}/all?X-Plex-Container-Start=0&X-Plex-Container-Size=10000")
    root = _xml_root(result)
    if root is None:
        return []

    items = []
    for item in _iter_videos(root):
        title = _attr(item, "title")
        rating_key = _attr(item, "ratingKey")
        key = _attr(item, "key")
        item_type = _attr(item, "type") or section_type
        year = _attr(item, "year")
        summary = _attr(item, "summary")
        guid = _attr(item, "guid")
        original_title = _attr(item, "originalTitle")

        # Skip empty container junk
        if not title or not rating_key:
            continue

        items.append({
            "title": title,
            "original_title": original_title,
            "year": year,
            "type": item_type,
            "ratingKey": rating_key,
            "key": key,
            "library": section_title,
            "libraryType": section_type,
            "guid": guid,
            "summary": summary[:300] if summary else "",
        })

    return items


def _scan_to_memory() -> str:
    libs = _list_libraries_data()
    if not libs:
        return "No Plex libraries found or Plex returned unreadable data."

    all_items = []
    scanned = []

    for lib in libs:
        ltype = lib.get("type", "")
        if ltype not in ("movie", "show"):
            continue

        section_items = _scan_library_section(lib["key"], lib["title"], ltype)
        all_items.extend(section_items)
        scanned.append(f"{lib['title']} ({ltype}): {len(section_items)} items")

    mem = {
        "scanned_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "server": _base_url(),
        "items": all_items,
    }
    _save_memory(mem)

    return (
        f"Plex memory scan complete.\n"
        f"Indexed {len(all_items)} items.\n" +
        "\n".join(f"  {line}" for line in scanned)
    )


def _search_memory(query: str, limit: int = 10) -> List[dict]:
    mem = _load_memory()
    items = mem.get("items", [])
    scored = []

    for item in items:
        title = item.get("title", "")
        year = item.get("year", "")
        score = _score_match(title, query, year)

        alt = item.get("original_title", "")
        if alt:
            score = max(score, _score_match(alt, query, year) - 5)

        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: (-x[0], x[1].get("title", "")))
    return [x[1] for x in scored[:limit]]


def _list_clients() -> List[dict]:
    """
    Gets Plex clients visible to the server.
    """
    result = _api("/clients")
    root = _xml_root(result)
    if root is None:
        return []

    clients = []
    for s in root.findall(".//Server"):
        clients.append({
            "name": _attr(s, "name"),
            "host": _attr(s, "host"),
            "address": _attr(s, "address"),
            "port": _attr(s, "port"),
            "machineIdentifier": _attr(s, "machineIdentifier"),
            "version": _attr(s, "version"),
            "product": _attr(s, "product"),
            "protocol": _attr(s, "protocol", "plex"),
        })
    return clients


def _find_client(name: str) -> Optional[dict]:
    target = _normalize(name)
    clients = _list_clients()

    for c in clients:
        if _normalize(c.get("name", "")) == target:
            return c
    for c in clients:
        if target in _normalize(c.get("name", "")):
            return c
    return None


def _build_play_queue_path(item: dict) -> str:
    """
    Creates a play queue for a movie/show item.
    This is more reliable than trying to fire raw play directly.
    """
    item_key = item.get("key", "")
    rating_key = item.get("ratingKey", "")
    if not item_key or not rating_key:
        return ""

    # Plex usually accepts uri=server://machineIdentifier/com.plexapp.plugins.library/library/metadata/{ratingKey}
    machine_id = _server_machine_id()
    if not machine_id:
        return ""

    uri = f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{rating_key}"
    return (
        "/playQueues"
        f"?type=video"
        f"&shuffle=0"
        f"&repeat=0"
        f"&continuous=0"
        f"&own=1"
        f"&uri={urllib.parse.quote(uri, safe='')}"
    )


def _play_from_memory(query: str, client_name: str = "") -> str:
    if not query:
        return "Usage: play <title>"

    matches = _search_memory(query, limit=5)
    if not matches:
        return (
            f"No cached Plex match for '{query}'.\n"
            f"Run 'scan' first or use 'search' for a live Plex search."
        )

    best = matches[0]

    # Ambiguity guard
    same_title = [m for m in matches if _normalize(m.get("title", "")) == _normalize(best.get("title", ""))]
    if len(matches) > 1 and matches[0].get("title") != matches[1].get("title"):
        preview = "\n".join(
            f"  {m.get('title')} ({m.get('year') or '?'}) [{m.get('type')}]"
            for m in matches[:5]
        )
        # Still proceed with top hit if it is strong enough
        if _score_match(best.get("title", ""), query, best.get("year", "")) < 90:
            return f"Multiple matches for '{query}':\n{preview}"

    cfg = _load_config()
    chosen_client = client_name.strip() or str(cfg.get("default_client", "")).strip()
    if not chosen_client:
        return (
            f"Resolved '{query}' to: {best.get('title')} ({best.get('year') or '?'}) [{best.get('type')}]\n"
            f"But no Plex client was specified. Use a configured default_client or ask for 'clients'."
        )

    client = _find_client(chosen_client)
    if not client:
        available = _list_clients()
        if available:
            names = "\n".join(f"  {c.get('name')}" for c in available)
            return f"Client '{chosen_client}' not found.\nAvailable clients:\n{names}"
        return f"Client '{chosen_client}' not found and no Plex clients were detected."

    play_queue_path = _build_play_queue_path(best)
    if not play_queue_path:
        return f"Could not build play queue for '{best.get('title')}'."

    pq_result = _api(play_queue_path, method="POST")
    pq_root = _xml_root(pq_result)
    if pq_root is None:
        return f"Failed creating play queue for '{best.get('title')}': {pq_result[:300]}"

    play_queue_id = _attr(pq_root, "playQueueID")
    if not play_queue_id:
        return f"Failed creating play queue for '{best.get('title')}'."

    # Proxy playback command through Plex server to the client
    machine_id = _server_machine_id()
    command = (
        f"/player/playback/playMedia"
        f"?machineIdentifier={urllib.parse.quote(machine_id)}"
        f"&key={urllib.parse.quote(best.get('key', ''))}"
        f"&offset=0"
        f"&type=video"
        f"&protocol=http"
        f"&address={urllib.parse.quote(str(_load_config().get('ip', '')))}"
        f"&port={urllib.parse.quote(str(_load_config().get('port', 32400)))}"
        f"&containerKey={urllib.parse.quote(f'/playQueues/{play_queue_id}?window=100&own=1')}"
    )

    # Client endpoint via proxy
    client_identifier = client.get("machineIdentifier", "")
    if not client_identifier:
        return f"Client '{chosen_client}' has no machineIdentifier."

    proxy_path = f"/system/players/{urllib.parse.quote(client_identifier)}/application/playMedia"
    # Fallback: many setups instead use resources under /player/playback/playMedia with X-Plex-Target-Client-Identifier
    # We try the more common playback route first.
    result = _api(
        command,
        method="GET",
    )

    if result.startswith("Error:"):
        return (
            f"Resolved '{query}' to '{best.get('title')}', but playback command failed.\n"
            f"Client: {client.get('name')}\n"
            f"Error: {result}"
        )

    return (
        f"Trying to play '{best.get('title')}'"
        f"{f' ({best.get('year')})' if best.get('year') else ''}"
        f" on {client.get('name')}."
    )


def exec_plex(action: str, query: str = "", client: str = "") -> str:
    """Control Plex Media Server."""
    action = (action or "").lower().strip()

    if action == "status":
        result = _api("/")
        root = _xml_root(result)
        if root is None:
            return result

        name = _attr(root, "friendlyName") or "Unknown"
        version = _attr(root, "version") or "?"
        machine_id = _attr(root, "machineIdentifier") or "?"
        sessions = _api("/status/sessions")
        session_root = _xml_root(sessions)
        session_count = len(session_root.findall(".//Video")) if session_root is not None else 0
        return f"Plex server: {name} v{version}\nMachine ID: {machine_id}\nActive streams: {session_count}"

    elif action == "libraries":
        libs = _list_libraries_data()
        if not libs:
            return "No libraries found."
        lines = [f"  {x['title']} ({x['type']})" for x in libs]
        return "Libraries:\n" + "\n".join(lines)

    elif action == "search":
        if not query:
            return "Usage: search <query>"

        encoded = urllib.parse.quote(query)
        result = _api(f"/hubs/search?query={encoded}&limit=10")
        root = _xml_root(result)
        if root is None:
            return result

        seen = set()
        out = []
        for elem in _iter_videos(root):
            title = _attr(elem, "title")
            year = _attr(elem, "year")
            etype = _attr(elem, "type")
            if title and title not in seen:
                seen.add(title)
                suffix = f" ({year})" if year else ""
                out.append(f"  {title}{suffix} [{etype or '?'}]")

        if out:
            return f"Search '{query}':\n" + "\n".join(out[:10])
        return f"No results for '{query}'."

    elif action == "scan":
        return _scan_to_memory()

    elif action in ("memory_search", "memory"):
        if not query:
            return "Usage: memory_search <query>"

        matches = _search_memory(query, limit=10)
        if not matches:
            return f"No cached results for '{query}'. Run 'scan' first."

        lines = []
        for m in matches:
            title = m.get("title", "?")
            year = m.get("year", "?")
            mtype = m.get("type", "?")
            lib = m.get("library", "?")
            lines.append(f"  {title} ({year}) [{mtype}] — {lib}")

        return f"Cached results for '{query}':\n" + "\n".join(lines)

    elif action == "recent":
        result = _api("/library/recentlyAdded?X-Plex-Container-Start=0&X-Plex-Container-Size=10")
        root = _xml_root(result)
        if root is None:
            return result

        titles = []
        for elem in _iter_videos(root):
            title = _attr(elem, "title")
            year = _attr(elem, "year")
            if title:
                titles.append(f"  {title}{f' ({year})' if year else ''}")

        if titles:
            return "Recently added:\n" + "\n".join(titles[:10])
        return "Nothing recently added."

    elif action == "ondeck":
        result = _api("/library/onDeck?X-Plex-Container-Start=0&X-Plex-Container-Size=10")
        root = _xml_root(result)
        if root is None:
            return result

        titles = []
        for elem in _iter_videos(root):
            title = _attr(elem, "title")
            year = _attr(elem, "year")
            if title:
                titles.append(f"  {title}{f' ({year})' if year else ''}")

        if titles:
            return "On Deck:\n" + "\n".join(titles[:10])
        return "Nothing on deck."

    elif action == "sessions":
        result = _api("/status/sessions")
        root = _xml_root(result)
        if root is None:
            return result

        rows = []
        for video in root.findall(".//Video"):
            media_title = _attr(video, "title")
            grandparent = _attr(video, "grandparentTitle")
            user = ""
            player = ""

            user_elem = video.find(".//User")
            if user_elem is not None:
                user = _attr(user_elem, "title")

            player_elem = video.find(".//Player")
            if player_elem is not None:
                player = _attr(player_elem, "title")

            if grandparent:
                media_title = f"{grandparent} — {media_title}"

            rows.append(f"  {media_title} on {player or '?'}{f' (user: {user})' if user else ''}")

        if rows:
            return "Now playing:\n" + "\n".join(rows)
        return "Nothing playing."

    elif action == "clients":
        clients = _list_clients()
        if not clients:
            return "No Plex clients found."

        lines = []
        for c in clients:
            lines.append(
                f"  {c.get('name')} — {c.get('product') or '?'} "
                f"{c.get('version') or ''} @ {c.get('host') or c.get('address') or '?'}:{c.get('port') or '?'}"
            )
        return "Plex clients:\n" + "\n".join(lines)

    elif action == "play":
        return _play_from_memory(query=query, client_name=client)

    elif action == "pause":
        sessions = _api("/status/sessions")
        root = _xml_root(sessions)
        if root is None:
            return sessions

        session_ids = []
        for video in root.findall(".//Video"):
            sk = _attr(video, "sessionKey")
            if sk:
                session_ids.append(sk)

        if not session_ids:
            return "Nothing playing to pause."

        errors = []
        for sid in session_ids:
            r = _api(f"/player/playback/pause?sessionId={sid}", method="PUT")
            if r.startswith("Error:"):
                errors.append(r)

        return "Paused." if not errors else "Pause sent, but some sessions returned errors."

    elif action == "resume":
        sessions = _api("/status/sessions")
        root = _xml_root(sessions)
        if root is None:
            return sessions

        session_ids = []
        for video in root.findall(".//Video"):
            sk = _attr(video, "sessionKey")
            if sk:
                session_ids.append(sk)

        if not session_ids:
            return "Nothing to resume."

        errors = []
        for sid in session_ids:
            r = _api(f"/player/playback/play?sessionId={sid}", method="PUT")
            if r.startswith("Error:"):
                errors.append(r)

        return "Resumed." if not errors else "Resume sent, but some sessions returned errors."

    elif action == "stop":
        sessions = _api("/status/sessions")
        root = _xml_root(sessions)
        if root is None:
            return sessions

        session_ids = []
        for video in root.findall(".//Video"):
            sk = _attr(video, "sessionKey")
            if sk:
                session_ids.append(sk)

        if not session_ids:
            return "Nothing playing to stop."

        errors = []
        for sid in session_ids:
            r = _api(f"/player/playback/stop?sessionId={sid}", method="PUT")
            if r.startswith("Error:"):
                errors.append(r)

        return "Stopped." if not errors else "Stop sent, but some sessions returned errors."

    else:
        return (
            f"Unknown action '{action}'. Available: "
            "status, libraries, search, scan, memory_search, recent, ondeck, "
            "sessions, clients, play, pause, resume, stop"
        )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "plex",
            "description": (
                "Control Plex Media Server. Actions: status, libraries, search, "
                "scan (index Plex into local memory), memory_search, recent, ondeck, "
                "sessions, clients, play, pause, resume, stop."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "libraries",
                            "search",
                            "scan",
                            "memory_search",
                            "recent",
                            "ondeck",
                            "sessions",
                            "clients",
                            "play",
                            "pause",
                            "resume",
                            "stop",
                        ],
                        "description": "Plex action to perform.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query or media title for search, memory_search, or play.",
                    },
                    "client": {
                        "type": "string",
                        "description": "Optional Plex client name for playback, e.g. 'Living Room Shield'.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "plex": exec_plex,
}

KEYWORDS = {
    "plex": [
        "plex",
        "media server",
        "movies",
        "tv shows",
        "recently added",
        "on deck",
        "what's playing",
        "search movie",
        "search show",
        "scan plex",
        "plex memory",
        "start movie on plex",
        "play on plex",
        "plex clients",
    ],
}

SKILL_EXAMPLES = [
    {"command": "scan plex", "tool": "plex", "args": {"action": "scan"}},
    {"command": "search cached plex for dune", "tool": "plex", "args": {"action": "memory_search", "query": "Dune"}},
    {"command": "show plex clients", "tool": "plex", "args": {"action": "clients"}},
    {"command": "play dune on plex", "tool": "plex", "args": {"action": "play", "query": "Dune"}},
    {"command": "play dune on living room shield", "tool": "plex", "args": {"action": "play", "query": "Dune", "client": "Living Room Shield"}},
]