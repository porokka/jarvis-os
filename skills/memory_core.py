"""
JARVIS Skill — Persistent memory core.

Handles:
- preferences (long-term identity)
- recent context (operational state)
- episodic logs (history)
- hybrid recall

Backends:
- JSON (fast exact access)
- Obsidian vault (human-readable logs)
- Mempalace (semantic recall, optional)
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SKILL_NAME = "memory"
SKILL_DESCRIPTION = "Persistent memory — preferences, context, episodic logs, semantic recall"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "core"
SKILL_TAGS = ["memory", "obsidian", "state", "semantic-recall", "mempalace"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "set_preference",
    "get_preference",
    "set_recent",
    "get_recent",
    "log_event",
    "recall",
    "planner_hint",
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
    "network_access": False,
    "entrypoint": "exec_memory",
    "config_file": "config/jarvis_memory_state.json",
    "mempalace_optional": True,
}


# --- Paths ---

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"

VAULT_DIR = Path("D:/Jarvis_vault") if os.name == "nt" else Path("/mnt/d/Jarvis_vault")

STATE_FILE = CONFIG_DIR / "jarvis_memory_state.json"
EVENT_LOG_DIR = VAULT_DIR / "Jarvis" / "Memory" / "Episodes"


# --- Defaults ---

DEFAULT_STATE = {
    "identity": {},
    "recent": {},
    "devices": {},
    "projects": {},
    "event_index": {
        "last_event_type": None,
        "last_event_at": None,
        "event_count": 0,
    },
}


# --- Init ---

def _ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    EVENT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> Dict:
    _ensure_dirs()
    if not STATE_FILE.exists():
        return dict(DEFAULT_STATE)

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT_STATE)

        merged = dict(DEFAULT_STATE)
        merged.update(data)

        # ensure required nested dicts exist
        for key in ("identity", "recent", "devices", "projects", "event_index"):
            if not isinstance(merged.get(key), dict):
                merged[key] = dict(DEFAULT_STATE[key])

        return merged
    except Exception:
        return dict(DEFAULT_STATE)


def _save_state(state: Dict) -> None:
    _ensure_dirs()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# --- Obsidian event logging ---

def _write_obsidian_event(event_type: str, data: Dict) -> Path:
    _ensure_dirs()

    now = datetime.now()
    date_file = EVENT_LOG_DIR / f"{now.strftime('%Y-%m-%d')}.md"

    entry = f"\n## {now.strftime('%H:%M:%S')} — {event_type}\n"
    for k, v in data.items():
        entry += f"- {k}: {v}\n"

    with open(date_file, "a", encoding="utf-8") as f:
        f.write(entry)

    return date_file


# --- Mempalace integration (optional) ---

def _build_event_text(event_type: str, data: Dict) -> str:
    """
    Convert a structured event into semantic text for embedding.
    """
    parts = [f"Event: {event_type}"]
    for k, v in data.items():
        parts.append(f"{k}: {v}")
    return " | ".join(parts)


def _mempalace_add_text(text: str, metadata: Dict) -> bool:
    """
    Best-effort semantic write.
    Adapters supported:
    1. module mempalace with function add(text=..., metadata=...)
    2. module mempalace with function store(text=..., metadata=...)
    3. skills.mempalace with same
    """
    try:
        try:
            import mempalace  # type: ignore
        except Exception:
            from skills import mempalace  # type: ignore

        if hasattr(mempalace, "add"):
            mempalace.add(text=text, metadata=metadata)
            return True

        if hasattr(mempalace, "store"):
            mempalace.store(text=text, metadata=metadata)
            return True

        return False
    except Exception:
        return False


def _mempalace_search(query: str, top_k: int = 8) -> List[Dict]:
    """
    Best-effort semantic search.
    Returns a normalized list of dicts.
    Adapters supported:
    1. mempalace.search(query=..., top_k=...)
    2. mempalace.search(query, top_k)
    """
    try:
        try:
            import mempalace  # type: ignore
        except Exception:
            from skills import mempalace  # type: ignore

        results = None

        if hasattr(mempalace, "search"):
            try:
                results = mempalace.search(query=query, top_k=top_k)
            except TypeError:
                results = mempalace.search(query, top_k)

        if not results:
            return []

        normalized = []
        for item in results:
            if isinstance(item, dict):
                normalized.append({
                    "text": item.get("text", ""),
                    "metadata": item.get("metadata", {}) or {},
                    "score": item.get("score"),
                })
            else:
                normalized.append({
                    "text": str(item),
                    "metadata": {},
                    "score": None,
                })
        return normalized
    except Exception:
        return []


def write_mempalace_embedding(text: str, metadata: Dict) -> bool:
    """
    Public helper for semantic writes.
    """
    return _mempalace_add_text(text=text, metadata=metadata)


# --- Query routing helpers ---

_VAGUE_QUERY_PATTERNS = [
    r"\bsimilar\b",
    r"\blike last time\b",
    r"\byesterday\b",
    r"\blast week\b",
    r"\bwhat did we do\b",
    r"\bremember\b",
    r"\brecall\b",
    r"\bsomething like\b",
    r"\bthat thing\b",
    r"\bthe one\b",
    r"\bagain\b",
    r"\bhistory\b",
]

_EXACT_QUERY_PATTERNS = [
    r"^[a-zA-Z0-9_.-]+$",
    r"\blast_[a-z0-9_]+\b",
    r"\bdefault_[a-z0-9_]+\b",
    r"\bpreferred_[a-z0-9_]+\b",
]


def planner_should_use_semantic_recall(query: str) -> bool:
    """
    Planner helper:
    - vague/natural-language/history-style questions -> semantic recall
    - exact key lookups -> JSON exact recall
    """
    q = (query or "").strip().lower()
    if not q:
        return False

    for pattern in _VAGUE_QUERY_PATTERNS:
        if re.search(pattern, q):
            return True

    for pattern in _EXACT_QUERY_PATTERNS:
        if re.search(pattern, q):
            return False

    # heuristic: long natural language queries are more likely semantic
    if len(q.split()) >= 4:
        return True

    return False


# --- Core operations ---

def remember_preference(key: str, value: Any) -> str:
    state = _load_state()
    state["identity"][key] = value
    _save_state(state)

    log_event("set_preference", {"key": key, "value": value}, write_semantic=True, write_json_index=False)
    return f"Saved preference: {key} = {value}"


def get_preference(key: str) -> Optional[Any]:
    state = _load_state()
    return state["identity"].get(key)


def set_recent(key: str, value: Any) -> str:
    state = _load_state()
    state["recent"][key] = value
    _save_state(state)
    return f"Updated context: {key}"


def get_recent(key: str) -> Optional[Any]:
    state = _load_state()
    return state["recent"].get(key)


def _write_event_index(state: Dict, event_type: str) -> None:
    event_index = state.get("event_index", {})
    event_index["last_event_type"] = event_type
    event_index["last_event_at"] = datetime.now().isoformat(timespec="seconds")
    event_index["event_count"] = int(event_index.get("event_count", 0) or 0) + 1
    state["event_index"] = event_index


def log_event(
    event_type: str,
    data: Dict,
    write_semantic: bool = True,
    write_json_index: bool = True,
) -> str:
    """
    Hybrid event logger:
    - writes Obsidian event log
    - updates small JSON event index
    - writes semantic embedding to Mempalace when available
    """
    if not isinstance(data, dict):
        data = {"value": str(data)}

    obsidian_file = _write_obsidian_event(event_type, data)

    if write_json_index:
        state = _load_state()
        _write_event_index(state, event_type)
        _save_state(state)

    mem_ok = False
    if write_semantic:
        text = _build_event_text(event_type, data)
        mem_ok = write_mempalace_embedding(
            text=text,
            metadata={
                "type": "event",
                "event_type": event_type,
                "source": "memory_core",
                "obsidian_file": str(obsidian_file),
                **data,
            },
        )

    return f"Logged event: {event_type}" + (" [semantic]" if mem_ok else "")


def _recall_exact(query: str) -> List[str]:
    state = _load_state()
    results = []
    q = query.lower()

    for section_name in ("identity", "recent", "devices", "projects"):
        section = state.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for k, v in section.items():
            if q in str(k).lower() or q in str(v).lower():
                results.append(f"[{section_name}] {k}: {v}")

    return results[:20]


def _recall_semantic(query: str, top_k: int = 6) -> List[str]:
    results = _mempalace_search(query=query, top_k=top_k)
    lines = []

    for item in results[:top_k]:
        text = str(item.get("text", "")).strip()
        md = item.get("metadata", {}) or {}
        score = item.get("score")
        label = md.get("event_type") or md.get("type") or "memory"

        prefix = f"[semantic:{label}]"
        if score is not None:
            try:
                prefix += f" ({float(score):.3f})"
            except Exception:
                pass

        if text:
            lines.append(f"{prefix} {text}")

    return lines


def recall(query: str) -> str:
    """
    Hybrid recall:
    - exact queries prefer JSON
    - vague/history-style queries prefer Mempalace
    - falls back gracefully if semantic layer unavailable
    """
    if not query or not query.strip():
        return "Error: query required"

    query = query.strip()

    use_semantic = planner_should_use_semantic_recall(query)

    if use_semantic:
        semantic = _recall_semantic(query)
        if semantic:
            return "\n".join(semantic)

        exact = _recall_exact(query)
        if exact:
            return "\n".join(exact)

        return f"No memory found for '{query}'"

    exact = _recall_exact(query)
    if exact:
        return "\n".join(exact)

    semantic = _recall_semantic(query)
    if semantic:
        return "\n".join(semantic)

    return f"No memory found for '{query}'"


# --- Tool executor ---

def exec_memory(
    action: str,
    key: str = "",
    value: str = "",
    event_type: str = "",
    data: dict = None,
    query: str = "",
) -> str:

    action = (action or "").lower().strip()

    if action == "set_preference":
        if not key:
            return "Error: key required"
        return remember_preference(key, value)

    if action == "get_preference":
        if not key:
            return "Error: key required"
        val = get_preference(key)
        return f"{key} = {val}" if val is not None else f"No preference for {key}"

    if action == "set_recent":
        if not key:
            return "Error: key required"
        return set_recent(key, value)

    if action == "get_recent":
        if not key:
            return "Error: key required"
        val = get_recent(key)
        return f"{key} = {val}" if val is not None else f"No recent value for {key}"

    if action == "log_event":
        if not event_type:
            return "Error: event_type required"
        return log_event(event_type, data or {})

    if action == "recall":
        if not query:
            return "Error: query required"
        return recall(query)

    if action == "planner_hint":
        if not query:
            return "Error: query required"
        return (
            "semantic"
            if planner_should_use_semantic_recall(query)
            else "exact"
        )

    return (
        "Available actions:\n"
        "- set_preference\n"
        "- get_preference\n"
        "- set_recent\n"
        "- get_recent\n"
        "- log_event\n"
        "- recall\n"
        "- planner_hint"
    )


# --- Tool definition ---

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory",
            "description": (
                "Persistent Jarvis memory system with hybrid recall. "
                "Stores preferences, exact state, episodic logs, and optional semantic memory via Mempalace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "event_type": {"type": "string"},
                    "data": {"type": "object"},
                    "query": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    }
]

TOOL_MAP = {"memory": exec_memory}

KEYWORDS = {
    "memory": [
        "remember",
        "recall",
        "what did i say",
        "preference",
        "context",
        "last time",
        "history",
        "mempalace",
        "semantic memory",
    ],
}