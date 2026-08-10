"""
JARVIS OS — Memory Router
/jarvis/memory/memory_router.py

Replaces live_model. Pass 1 now returns the full live_model schema
(speak, transcript, intent, action, route, tool, confidences, args)
in addition to memory classification.

Memory types:
  recent_chat  — this conversation / last few turns (in-context)
  chat_log     — exact old wording, previous commands, debugging history
  qdrant       — semantic memory, concepts, decisions, summaries
  obsidian     — durable notes, project docs, plans
  files        — code/config source of truth
  tools        — live action or device state (caller handles, not fetched here)

Flow:
  Pass 1 — classify + live routing: intent, action, route, tool, args,
            confidences, speak, transcript, need_memory, memory_types
  Pass 2 — build fetch plan per type  (only if need_memory=true)
  Pass 3 — fetch all types            (only if need_memory=true)
  Pass 4 — summarize into one context block (only if need_memory=true)

Return from route():
  result (dict) — full live_model-equivalent output + memory context block
  meta   (dict) — routing metadata for logging
"""

import json
import os
import requests
from pathlib import Path
from qdrant_client import QdrantClient

# Redis for recent_chat — optional, degrades gracefully
try:
    import redis as _redis_lib
    _redis_client = _redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
    _redis_client.ping()
    _REDIS_OK = True
except Exception:
    _redis_client = None
    _REDIS_OK = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLLAMA_BASE   = "http://127.0.0.1:11434"
EMBED_MODEL   = "nomic-embed-text"

LLAMA_CPP_BASE = os.environ.get("LLAMA_CPP_HOST", "http://127.0.0.1:8091")
FAST_MODEL     = "gemma4:4b"   # label only — llama.cpp serves whatever is loaded

QDRANT_HOST  = "127.0.0.1"
QDRANT_PORT  = 6333
# jarvis_lessons: distilled nightly by reflection_daemon.py — retrieved
# alongside normal memory, ranked by similarity × lesson strength.
QDRANT_COLS  = ["jarvis_sessions", "jarvis_memory", "jarvis_lessons"]
OBSIDIAN_DIR = Path("/mnt/d/Jarvis_vault")
CHAT_LOG_PATH = Path("/mnt/d/Jarvis_vault/chat_log.jsonl")
TOP_K        = 5
SCORE_MIN    = 0.55
# chat_only and memory paths must meet this threshold; 0.9 escalated almost
# every chat to planner (slow). Overridable without code changes.
CHAT_CONFIDENCE_MIN = float(os.environ.get("JARVIS_CHAT_CONFIDENCE_MIN", "0.75"))
# Pass 2 (fetch-plan) LLM call: off by default — the fallback plan (query =
# user message per requested type) is nearly always what the LLM returned
# anyway, and skipping it saves one Gemma round-trip per memory fetch.
FETCH_PLAN_USE_LLM = os.environ.get("JARVIS_FETCH_PLAN_LLM", "0") == "1"

REACT_HOST   = "http://127.0.0.1:7900"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FALLBACK_ROUTER_MODEL = os.environ.get("JARVIS_ROUTER_FALLBACK_MODEL", "qwen3:14b")


def _llama(prompt: str, system: str, timeout: int = 20) -> str:
    """Call llama.cpp server (Gemma 4B) for fast routing passes.
    Falls back to Ollama when llama.cpp is down — with the Claude proxy on
    :11434 that fallback transparently runs on the cloud."""
    try:
        resp = requests.post(f"{LLAMA_CPP_BASE}/v1/chat/completions", json={
            "model":       "gemma",
            "messages": [
                {"role": "system",  "content": system},
                {"role": "user",    "content": prompt}
            ],
            "temperature": 0.1,
            "stream":      False
        }, timeout=timeout)
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if "<think>" in raw:
            raw = raw.split("</think>")[-1].strip()
        return raw
    except Exception as llama_err:
        try:
            resp = requests.post(f"{OLLAMA_BASE}/api/chat", json={
                "model": FALLBACK_ROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt}
                ],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.1},
            }, timeout=max(timeout, 60))
            raw = resp.json()["message"]["content"].strip()
            if "<think>" in raw:
                raw = raw.split("</think>")[-1].strip()
            print(f"[ROUTER] llama.cpp down, used Ollama fallback ({FALLBACK_ROUTER_MODEL})")
            return raw
        except Exception:
            return f"ERROR: {llama_err}"


def _embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(f"{OLLAMA_BASE}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text}, timeout=15)
        return resp.json().get("embedding")
    except Exception:
        return None


def _parse_json(raw: str) -> dict | list | None:
    try:
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _empty_live() -> dict:
    """Safe fallback live_model output on parse failure."""
    return {
        "speak":                  "I didn't catch that, could you repeat?",
        "transcript":             "",
        "intent":                 "unknown",
        "action":                 "chat_only",
        "route":                  "live",
        "tool":                   None,
        "chat_confidence":        0.5,
        "escalation_confidence":  0.0,
        "execute_confidence":     0.0,
        "need_memory":            False,
        "memory_confidence":      0.0,
        "args":                   {},
        "memory_types":           [],
    }

# ---------------------------------------------------------------------------
# Pass 1 — classify + live routing (replaces live_model)
# ---------------------------------------------------------------------------

CLASSIFY_SYSTEM = """You are the brain of JARVIS, a local AI assistant.
Your job is to analyse the user's message and return a single JSON object that:
  1. Decides how to route and respond (live_model fields)
  2. Decides whether memory retrieval is needed and which types

─── ROUTING FIELDS ──────────────────────────────────────────────────────────

speak        — short natural sentence to say to the user RIGHT NOW
               (acknowledgement, answer, or "let me check that")
transcript   — cleaned, normalised version of the user command/message
intent       — short_snake_case label, e.g. play_music, check_service, run_tests
action       — one of:
                 chat_only     simple answer, no tool, no memory needed
                 direct_tool   call a specific tool immediately
                 planner       multi-step plan needed
                 deep_agent    research goal needing evidence from 2+ sources/tools
                 code          write or run code

IMPORTANT — use action="code" and route="code" when user says:
  - "build X", "create X", "make X", "write X", "code X", "develop X"
  - "build a website", "build a game", "build an app", "build a tool"
  - Any request to generate, write, or produce a file, script, or program
  - "fix X file", "update X.py", "patch X", "edit X code"
  Never use chat_only for requests to BUILD or CREATE software/files.

IMPORTANT — use action="deep_agent" and route="deep" when a good answer
requires gathering evidence from TWO OR MORE sources or tools first.
The deep agent plans its own tool calls (web search, market data, news,
calendars) and synthesises the results. Choose it for:
  - Forecasts / outlooks: "how do stock markets look next week",
    "what's the outlook for X", "predict/estimate Y for the coming month"
  - Comparative research: "compare X and Y", "should I do X or Y",
    "is now a good time to X" — anything hinging on current facts
  - Any question you cannot answer well from one tool call or from
    knowledge alone (needs current data + news + calendar combined)
  Never answer these with chat_only, and never reduce them to a single
  direct_tool call — one web search is not research.
route        — one of:
                 live          chat / immediate answer
                 tools         tool dispatch
                 reason        needs reasoning / memory
                 code          code generation or execution
                 deep          deep research or multi-step agent
tool         — exact tool function name if action=direct_tool, else null
args         — tool arguments dict if action=direct_tool, else {}
chat_confidence       — 0.0–1.0, how confident this is a pure chat response
escalation_confidence — 0.0–1.0, how likely this needs escalation to bigger model
execute_confidence    — 0.0–1.0, how confident a tool should be executed now

─── MEMORY FIELDS ───────────────────────────────────────────────────────────

need_memory        — true | false
memory_confidence  — 0.0–1.0
memory_types       — list of memory source objects (see below), [] if not needed

Memory types and when to use them:
  recent_chat  — this conversation / last few turns (already in context window)
  chat_log     — exact old wording, previous commands, debugging history
  qdrant       — semantic memory: past decisions, project summaries, concepts
  obsidian     — durable notes: project docs, plans, recipes, long-form notes
  files        — code or config files, source of truth for technical details
  tools        — live action or device state (use for direct_tool routing)

Set need_memory: false when:
  - Pure chat, general knowledge, or simple commands with no context dependency
  - action is direct_tool (tool dispatch does not need memory retrieval)

Set need_memory: true when:
  - References past events, conversations, prior commands, or project history
  - Requires personal or project-specific context JARVIS might have stored
  - You would otherwise say "I don't have that information"

─── AMBIGUOUS / FOLLOW-UP REPLIES ──────────────────────────────────────────

ALWAYS set need_memory: true and include recent_chat (and chat_log) when:
  - The message is a single digit or number ("1", "2", "3" ... "6")
  - The message is a short follow-up word: "yes", "no", "ok", "more", "next",
    "continue", "details", "that one", "which one", "the first", etc.
  - The message is 1-2 words that only make sense with prior context
  - The message is a bare acknowledgement: "correct", "right", "agreed"

For these, NEVER return chat_only with need_memory: false. The model cannot
answer without knowing what the user is referring to.

─── RESPONSE FORMAT ─────────────────────────────────────────────────────────

Respond ONLY with valid JSON, no explanation, no markdown fences:
{
  "speak":                 "I'll check that for you.",
  "transcript":            "cleaned user message",
  "intent":                "short_snake_case_intent",
  "action":                "chat_only|direct_tool|planner|code|deep_agent",
  "route":                 "live|tools|reason|code|deep",
  "tool":                  null,
  "chat_confidence":       0.95,
  "escalation_confidence": 0.02,
  "execute_confidence":    0.02,
  "need_memory":           false,
  "memory_confidence":     0.1,
  "args":                  {},
  "memory_types": [
    {"type": "qdrant",   "reason": "past project decisions may be stored"},
    {"type": "obsidian", "reason": "project plans likely in vault"}
  ]
}

If need_memory is false, memory_types must be [].
"""


# ---------------------------------------------------------------------------
# Recent chat fetcher — reads Redis working memory
# ---------------------------------------------------------------------------

def fetch_recent_chat_from_redis(max_items: int = 8) -> list[dict]:
    """Pull last N turns from Redis working memory (agent:memory:working)."""
    if not _REDIS_OK or _redis_client is None:
        return []
    try:
        items = _redis_client.lrange("agent:memory:working", -max_items, -1)
        results = []
        for item in items:
            if item and item.strip():
                results.append({
                    "type":   "recent_chat",
                    "score":  1.0,
                    "source": "redis:working_memory",
                    "text":   item[:500],
                })
        return results
    except Exception as e:
        print(f"[MEMORY] Redis recent_chat error: {e}")
        return []


_GREETINGS = {
    "hi", "hello", "hey",
    "good morning", "good afternoon", "good evening",
    "morning", "evening",
    "greetings",
}

_STANDALONE = {
    * _GREETINGS,
    "thanks",
    "thank you",
    "bye",
    "goodbye",
}

_AMBIGUOUS_PATTERNS = {
    # single digits or short numbers — follow-up selectors
    "single_digit": lambda t: t.isdigit() and len(t) <= 2,

    # yes/no/ack words
    "ack": lambda t: t in {
        "yes", "no", "ok", "okay", "sure", "nope",
        "yep", "yeah", "correct", "right",
        "exactly", "indeed", "fine", "agreed",
    },

    # follow-up words
    "followup": lambda t: t in {
        "more", "next", "continue", "go on",
        "proceed", "expand", "details",
        "tell me more", "and", "what else",
        "show me", "which one", "that one",
        "this one", "the first", "the second",
        "the third", "the last",
    },

    # very short messages that are NOT greetings
    "very_short": lambda t: (
        len(t.split()) <= 2
        and len(t) < 20
        and t not in _STANDALONE
    ),
}


def classify(user_input: str, recent_turns: list[str] | None = None) -> dict:
    """
    Pass 1 — single LLM call that replaces both live_model and old classify().
    Returns full live_model schema + memory_types.
    """
    # Always inject Redis working memory so Gemma has conversation context
    # for every call — short replies, follow-ups, and fresh requests alike.
    redis_turns = [item["text"] for item in fetch_recent_chat_from_redis(max_items=8)]
    if redis_turns:
        combined = redis_turns + (recent_turns or [])
        seen: set[str] = set()
        merged: list[str] = []
        for t in combined:
            if t not in seen:
                seen.add(t)
                merged.append(t)
        recent_turns = merged

    context = ""
    if recent_turns:
        context = "Recent conversation:\n" + "\n".join(recent_turns[-6:]) + "\n\n"

    result = _llama(f"{context}User message: {user_input}", CLASSIFY_SYSTEM)
    parsed = _parse_json(result)

    if not parsed:
        fallback = _empty_live()
        fallback["_parse_error"] = result[:200]
        if result.startswith("ERROR:"):
            # llama.cpp unreachable — don't mask it as a mishearing.
            # Route to reason so the main model still answers.
            fallback["speak"] = ""
            fallback["action"] = "planner"
            fallback["route"] = "reason"
            fallback["transcript"] = user_input
            print(f"[ROUTER] classify LLM failed, escalating to reason: {result[:120]}")
        return fallback

    defaults = _empty_live()
    for k, v in defaults.items():
        parsed.setdefault(k, v)

    return parsed

# ---------------------------------------------------------------------------
# Tool search — fetch live skills and match intent via Gemma
# ---------------------------------------------------------------------------

def fetch_available_tools() -> list[dict]:
    """Fetch live tool list from /api/skills."""
    try:
        resp = requests.get(f"{REACT_HOST}/api/skills", timeout=3)
        data = resp.json()
        return data.get("skills", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"[MEMORY] fetch_available_tools error: {e}")
        return []


TOOL_MATCH_SYSTEM = """You are a tool matcher for JARVIS, a local AI assistant.
Given a user intent and a list of available skills/tools, find the best match.

Respond ONLY with valid JSON, no explanation:
{
  "matched":    true,
  "skill":      "skill_name",
  "tool":       "tool_function_name",
  "confidence": "high|medium|low",
  "reason":     "one sentence"
}

If nothing matches:
{
  "matched":    false,
  "skill":      null,
  "tool":       null,
  "confidence": "low",
  "reason":     "no matching tool found"
}
"""


def match_tool(intent: str, skills: list[dict]) -> dict:
    if not skills:
        return {"matched": False, "tool": None, "skill": None,
                "confidence": "low", "reason": "no skills loaded"}

    skill_lines = [
        f"- skill: {s['name']} | tools: {', '.join(s.get('tools', []))} "
        f"| desc: {s.get('description','')[:100]}"
        for s in skills
    ]
    prompt = f"User intent: {intent}\n\nAvailable skills:\n" + "\n".join(skill_lines)
    raw    = _llama(prompt, TOOL_MATCH_SYSTEM, timeout=15)
    parsed = _parse_json(raw)
    if not parsed:
        return {"matched": False, "tool": None, "skill": None,
                "confidence": "low", "reason": "parse error"}
    return parsed


def search_tools_for_intent(intent: str) -> dict:
    skills  = fetch_available_tools()
    matched = match_tool(intent, skills)
    matched["available_count"] = len(skills)
    return matched

# ---------------------------------------------------------------------------
# Pass 2 — build fetch plan
# ---------------------------------------------------------------------------

BUILD_QUERY_SYSTEM = """You are a search query builder for a multi-source memory system.
Given a user message and list of memory types, output a fetch plan.

Respond ONLY with valid JSON. Only include keys for the requested types. Null = skip.
{
  "qdrant":      {"query": "semantic phrase for vector search", "top_k": 5},
  "chat_log":    {"query": "keywords or phrase to match in chat history"},
  "obsidian":    {"query": "keywords to search vault notes"},
  "files":       {"query": "filename or code pattern"},
  "recent_chat": null,
  "tools":       null
}

recent_chat must be fetched when requested. Use {"query": "recent context"}.
tools are never fetched — always null.
Keep queries short and semantic, not the user's raw phrasing.
"""


def build_fetch_plan(user_input: str, memory_types: list[dict]) -> dict:
    type_names = [m["type"] for m in memory_types]

    # Hard rule: recent_chat must be fetched when requested
    fixed_plan = {}
    if "recent_chat" in type_names:
        fixed_plan["recent_chat"] = {"query": user_input}

    if "tools" in type_names:
        fixed_plan["tools"] = None

    parsed: dict = {}
    if FETCH_PLAN_USE_LLM:
        # Optional Pass-2 LLM refinement (env JARVIS_FETCH_PLAN_LLM=1)
        prompt = f"Memory types needed: {type_names}\nUser message: {user_input}"
        result = _llama(prompt, BUILD_QUERY_SYSTEM)
        parsed = _parse_json(result) or {}

    # Merge fixed rules, but do not allow the LLM to null recent_chat
    parsed.update(fixed_plan)

    for t in type_names:
        if t not in parsed:
            parsed[t] = {"query": user_input}

    return parsed

# ---------------------------------------------------------------------------
# Pass 3 — fetchers
# ---------------------------------------------------------------------------

def fetch_qdrant(query: str, top_k: int = TOP_K) -> list[dict]:
    embedding = _embed(query)
    if not embedding:
        return []
    q = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    existing = [c.name for c in q.get_collections().collections]
    results  = []
    for col in QDRANT_COLS:
        if col not in existing:
            continue
        try:
            try:
                hits = q.query_points(
                    collection_name=col,
                    query=embedding,
                    limit=top_k,
                    score_threshold=SCORE_MIN,
                    with_payload=True
                ).points
            except AttributeError:
                hits = q.search(
                    collection_name=col,
                    query_vector=embedding,
                    limit=top_k,
                    score_threshold=SCORE_MIN,
                    with_payload=True
                )
            for h in hits:
                sim = h.score
                # Lessons carry a reinforcement score (0.15..2.0) maintained
                # by the reflection daemon — weight similarity by strength so
                # a 5×-confirmed lesson outranks a decayed one-off.
                if col == "jarvis_lessons":
                    strength = float(h.payload.get("score", 1.0) or 1.0)
                    sim = sim * (0.6 + 0.2 * min(strength, 2.0))
                results.append({
                    "type":   "lesson" if col == "jarvis_lessons" else "qdrant",
                    "score":  round(sim, 3),
                    "source": h.payload.get("source", col),
                    "text":   h.payload.get("text", h.payload.get("lesson", "")),
                    "task":   h.payload.get("task", ""),
                    "steps":  h.payload.get("steps", []),
                })
        except Exception as e:
            print(f"[MEMORY] Qdrant error ({col}): {e}")
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def fetch_chat_log(query: str, max_results: int = 5) -> list[dict]:
    if not CHAT_LOG_PATH.exists():
        return []
    results = []
    terms   = query.lower().split()
    try:
        for line in reversed(CHAT_LOG_PATH.read_text().splitlines()):
            if not line.strip():
                continue
            try:
                entry   = json.loads(line)
                content = entry.get("content", "").lower()
                if any(t in content for t in terms):
                    results.append({
                        "type":   "chat_log",
                        "score":  1.0,
                        "source": "chat_log.jsonl",
                        "text":   entry.get("content", "")[:500],
                        "ts":     entry.get("ts", "")
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
    except Exception as e:
        print(f"[MEMORY] chat_log error: {e}")
    return results


def fetch_obsidian(query: str, max_results: int = 5) -> list[dict]:
    if not OBSIDIAN_DIR.exists():
        return []
    results = []
    terms   = query.lower().split()
    try:
        for md in sorted(OBSIDIAN_DIR.rglob("*.md"),
                         key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                text    = md.read_text(encoding="utf-8", errors="ignore")
                lines   = text.splitlines()
                low     = [l.lower() for l in lines]
                if any(t in l for t in terms for l in low):
                    snippets = []
                    seen     = set()
                    for i, l in enumerate(low):
                        if any(t in l for t in terms):
                            start = max(0, i - 5)
                            end   = min(len(lines), i + 6)
                            key   = (start, end)
                            if key not in seen:
                                seen.add(key)
                                snippets.append("\n".join(lines[start:end]))
                    results.append({
                        "type":   "obsidian",
                        "score":  1.0,
                        "source": str(md.relative_to(OBSIDIAN_DIR)),
                        "text":   "\n---\n".join(snippets[:3])[:600]
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
    except Exception as e:
        print(f"[MEMORY] Obsidian error: {e}")
    return results


def fetch_files(query: str, **_) -> list[dict]:
    return [{"type": "files", "score": 1.0, "source": "file_search",
             "text": f"File search needed: {query}"}]


FETCHERS = {
    "qdrant":      lambda plan: fetch_qdrant(plan["query"], plan.get("top_k", TOP_K)),
    "chat_log":    lambda plan: fetch_chat_log(plan["query"]),
    "obsidian":    lambda plan: fetch_obsidian(plan["query"]),
    "files":       lambda plan: fetch_files(plan["query"]),
    "recent_chat": lambda plan: fetch_recent_chat_from_redis(max_items=8),
    "tools":       lambda plan: [],
}


def fetch_all(fetch_plan: dict) -> list[dict]:
    results = []
    for mem_type, plan in fetch_plan.items():
        if not plan:
            continue
        fetcher = FETCHERS.get(mem_type)
        if not fetcher:
            continue
        try:
            results.extend(fetcher(plan))
        except Exception as e:
            print(f"[MEMORY] fetch error ({mem_type}): {e}")
    return results

# ---------------------------------------------------------------------------
# Pass 4 — summarize
# ---------------------------------------------------------------------------

SUMMARIZE_SYSTEM = """You are a memory summarizer for JARVIS, a local AI assistant.
Compress retrieved memory results into a clean context block for the main model.

Rules:
- Summarize ALL results — the retrieval system already filtered for relevance
- Only discard a result if it is pure noise with zero connection to the question
- Include dates, task names, decisions, steps — concrete details are valuable
- Under 300 words total
- Group by source type with a short label
- Plain text, no JSON
- Start with: RETRIEVED MEMORY:
- Only write "RETRIEVED MEMORY: none relevant" if every single result is completely unrelated noise
- Do not explain what you are doing or repeat the question
"""


def summarize_context(user_input: str, results: list[dict]) -> str:
    if not results:
        return "RETRIEVED MEMORY: none relevant"

    by_type: dict[str, list] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)

    blocks     = []
    total_chars = 0
    for mem_type, items in by_type.items():
        block = f"[{mem_type.upper()}]\n"
        for item in items:
            entry = ""
            if item.get("source"):
                entry += f"source: {item['source']}"
            if item.get("score") and item["score"] != 1.0:
                entry += f" (score: {item['score']})"
            entry += "\n"
            if item.get("task"):
                entry += f"task: {item['task']}\n"
            if item.get("steps"):
                entry += "steps: " + " → ".join(item["steps"][:5]) + "\n"
            if item.get("text"):
                entry += item["text"][:400] + "\n"
            block       += entry + "\n"
            total_chars += len(entry)
        blocks.append(block)

    raw_context = "RETRIEVED MEMORY:\n" + "\n---\n".join(blocks)

    if total_chars > 1200:
        prompt = (
            f"User question: {user_input}\n\n"
            f"Memory results (compress to under 300 words, keep all dates/tasks/decisions):\n\n"
            + "\n---\n".join(blocks)
        )
        compressed = _llama(prompt, SUMMARIZE_SYSTEM, timeout=30)
        if compressed and len(compressed) > 20:
            if not compressed.startswith("RETRIEVED MEMORY"):
                compressed = f"RETRIEVED MEMORY:\n{compressed}"
            return compressed

    return raw_context

# ---------------------------------------------------------------------------
# Full pipeline — replaces live_model + old route()
# ---------------------------------------------------------------------------

def _log_interaction(user_input: str, result: dict) -> None:
    """Push the exchange to jarvis:log:<date> for the nightly reflection
    pass (reflection_daemon.py). Never raises."""
    if not _REDIS_OK or _redis_client is None:
        return
    try:
        from datetime import datetime as _dt
        now = _dt.now()
        key = f"jarvis:log:{now.strftime('%Y-%m-%d')}"
        _redis_client.rpush(key, json.dumps({
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": "chat",
            "user": user_input[:300],
            "action": (
                f"route={result.get('route')} action={result.get('action')}"
                + (f" tool={result.get('tool')}" if result.get("tool") else "")
            ),
            "outcome": "success",
            "detail": "",
        }))
        _redis_client.expire(key, 7 * 86400)
    except Exception:
        pass


def route(user_input: str, recent_turns: list[str] | None = None) -> tuple[dict, dict]:
    result, meta = _route_impl(user_input, recent_turns)
    _log_interaction(user_input, result)
    return result, meta


def _route_impl(user_input: str, recent_turns: list[str] | None = None) -> tuple[dict, dict]:
    """
    Full pipeline: classify + route + optional memory fetch.

    Replaces both live_model and the old route() function.

    Args:
        user_input:   current user message
        recent_turns: last N turns as strings

    Returns:
        result (dict) — full live_model-equivalent output:
                         speak, transcript, intent, action, route, tool,
                         chat_confidence, escalation_confidence, execute_confidence,
                         need_memory, memory_confidence, args,
                         memory_context (str, empty if not needed)
        meta   (dict) — routing metadata for logging
    """

    # ── Pass 1: classify + live routing ──────────────────────────────────
    classification = classify(user_input, recent_turns)

    # Extract live_model fields
    result: dict = {
        "speak":                  classification.get("speak", ""),
        "transcript":             classification.get("transcript", user_input),
        "intent":                 classification.get("intent", "unknown"),
        "action":                 classification.get("action", "chat_only"),
        "route":                  classification.get("route", "live"),
        "tool":                   classification.get("tool"),
        "chat_confidence":        classification.get("chat_confidence", 0.5),
        "escalation_confidence":  classification.get("escalation_confidence", 0.0),
        "execute_confidence":     classification.get("execute_confidence", 0.0),
        "need_memory":            classification.get("need_memory", False),
        "memory_confidence":      classification.get("memory_confidence", 0.0),
        "args":                   classification.get("args", {}),
        "memory_context":         "",   # filled by passes 2-4 if needed
    }

    memory_types = classification.get("memory_types", [])

    meta: dict = {
        "pass1_ok":   "_parse_error" not in classification,
        "intent":     result["intent"],
        "action":     result["action"],
        "route":      result["route"],
        "need_memory": result["need_memory"],
    }

    # ── Tool dispatch path ────────────────────────────────────────────────
    # If Pass 1 identified a direct tool, optionally verify against live skills
    if result["action"] == "direct_tool" and not result["tool"]:
        # tool name wasn't resolved — search live skills
        tool_types = [m for m in memory_types if m.get("type") == "tools"]
        for td in tool_types:
            intent  = td.get("intent") or td.get("reason") or user_input
            matched = search_tools_for_intent(intent)
            if matched.get("matched"):
                result["tool"] = matched["tool"]
                result["args"] = result["args"] or {}
                meta["tool_search"] = matched
                print(f"[ROUTER] tool resolved: {matched['skill']}.{matched['tool']} "
                      f"(confidence={matched['confidence']})")
                break

    # ── Confidence gate — chat_only and memory paths ─────────────────────
    # If the final action is chat_only (no tool, no escalation), or the route
    # is reason (memory path), chat_confidence must be >= CHAT_CONFIDENCE_MIN.
    # Anything below threshold gets escalated to planner/reason so the main
    # model can decide rather than returning a low-confidence chat answer.
    def _is_chat_final() -> bool:
        return result["action"] == "chat_only" or result["route"] == "reason"

    if _is_chat_final() and result["chat_confidence"] < CHAT_CONFIDENCE_MIN:
        result["action"]                = "planner"
        result["route"]                 = "reason"
        result["escalation_confidence"] = round(1.0 - result["chat_confidence"], 2)
        result["speak"]                 = "Let me think about that."
        meta["escalated"]               = True
        meta["escalation_reason"]       = (
            f"chat_confidence {result['chat_confidence']} < {CHAT_CONFIDENCE_MIN}"
        )
        print(f"[ROUTER] escalated: chat_confidence={result['chat_confidence']} "
              f"below threshold {CHAT_CONFIDENCE_MIN}")

    # ── No memory needed — return early ──────────────────────────────────
    if not result["need_memory"]:
        meta["routed"] = False
        meta["reasoning"] = "need_memory=false"
        return result, meta

    # ── Memory fetch path (Passes 2-4) ────────────────────────────────────
    fetch_types = [m for m in memory_types if m.get("type") != "tools"]

    if not fetch_types:
        meta["routed"]    = False
        meta["reasoning"] = "no fetch types after excluding tools"
        return result, meta

    # Pass 2 — build fetch plan
    fetch_plan = build_fetch_plan(user_input, fetch_types)
    meta["fetch_plan"] = fetch_plan

    # Pass 3 — fetch
    hits = fetch_all(fetch_plan)
    meta["hits"] = len(hits)
    meta["top_score"] = hits[0]["score"] if hits else 0

    # Pass 4 — summarize
    context = summarize_context(user_input, hits)
    result["memory_context"] = context

    # Second confidence gate — memory came back empty, still low confidence
    if context == "RETRIEVED MEMORY: none relevant" and _is_chat_final():
        if result["chat_confidence"] < CHAT_CONFIDENCE_MIN:
            result["action"]                = "planner"
            result["route"]                 = "reason"
            result["escalation_confidence"] = round(1.0 - result["chat_confidence"], 2)
            result["speak"]                 = "I don't have enough context, let me reason through this."
            meta["escalated"]               = True
            meta["escalation_reason"]       = "memory returned nothing, chat_confidence still low"
            print(f"[ROUTER] escalated after empty memory: chat_confidence={result['chat_confidence']}")

    meta["routed"]    = True
    meta["reasoning"] = classification.get("reasoning", "")
    meta["types"]     = [m["type"] for m in fetch_types]

    return result, meta

# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    test = " ".join(sys.argv[1:]) or "What did we work on yesterday?"
    print(f"\nInput: {test}\n{'='*60}")

    result, meta = route(test)

    print("\n[RESULT]")
    for k, v in result.items():
        if k == "memory_context":
            print(f"  memory_context:\n{v}")
        else:
            print(f"  {k}: {v}")

    print("\n[META]")
    print(json.dumps(meta, indent=2))