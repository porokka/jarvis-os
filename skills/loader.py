"""
Dynamic skill loader — discovers and imports all skill modules.

Usage:
    from skills import (
        load_skills,
        get_all_tools,
        get_all_tool_map,
        get_all_keywords,
        get_all_skill_meta,
        get_loaded_skills,
    )

    load_skills()           # import all enabled skills
    get_all_tools()         # merged TOOLS list for Ollama
    get_all_tool_map()      # merged {name: executor} dict
    get_all_keywords()      # merged {tool_name: [keywords]} dict
    get_all_skill_meta()    # merged {tool_name: metadata} dict
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SKILLS_DIR = Path(__file__).parent
CONFIG_PATH = SKILLS_DIR.parent / "config" / "skills.json"

# Registry — populated by load_skills()
_loaded_skills: List[Dict[str, Any]] = []


def _normalize_str_list(values: Any) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []

    out: List[str] = []
    for value in values:
        if isinstance(value, str):
            s = value.strip()
            if s:
                out.append(s)
    return out


def _tool_name(tool: Dict[str, Any]) -> Optional[str]:
    try:
        name = tool["function"]["name"]
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass
    return None


def _tool_description(tool: Dict[str, Any]) -> str:
    try:
        desc = tool["function"].get("description", "")
        return str(desc).strip() if desc is not None else ""
    except Exception:
        return ""


def _fallback_keywords(tool_name: str, tool: Dict[str, Any], existing: List[str]) -> List[str]:
    merged = list(existing)

    if tool_name:
        merged.append(tool_name)
        merged.append(tool_name.replace("_", " "))

    desc = _tool_description(tool)
    if desc:
        merged.append(desc)

    # dedupe while preserving order
    seen = set()
    out: List[str] = []
    for item in merged:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())

    return out


def _build_tool_meta(
    module_name: str,
    tool: Dict[str, Any],
    existing_keywords: List[str],
    skill_meta: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    tool_name = _tool_name(tool)
    if not tool_name:
        return None

    module_keywords = _normalize_str_list(skill_meta.get("keywords"))
    module_intent_aliases = _normalize_str_list(skill_meta.get("intent_aliases"))
    module_direct_match = _normalize_str_list(skill_meta.get("direct_match"))
    module_route = skill_meta.get("route") if isinstance(skill_meta.get("route"), str) else None

    per_tool_meta = skill_meta.get("tools", {})
    if not isinstance(per_tool_meta, dict):
        per_tool_meta = {}

    tool_meta_raw = per_tool_meta.get(tool_name, {})
    if not isinstance(tool_meta_raw, dict):
        tool_meta_raw = {}

    tool_keywords = _normalize_str_list(tool_meta_raw.get("keywords"))
    tool_intent_aliases = _normalize_str_list(tool_meta_raw.get("intent_aliases"))
    tool_direct_match = _normalize_str_list(tool_meta_raw.get("direct_match"))
    tool_route = tool_meta_raw.get("route") if isinstance(tool_meta_raw.get("route"), str) else None

    merged_keywords = _fallback_keywords(
        tool_name,
        tool,
        existing_keywords + module_keywords + tool_keywords,
    )

    merged_intent_aliases = []
    for item in module_intent_aliases + tool_intent_aliases:
        key = item.strip().lower()
        if key and key not in {x.lower() for x in merged_intent_aliases}:
            merged_intent_aliases.append(item.strip())

    merged_direct_match = []
    for item in module_direct_match + tool_direct_match:
        key = item.strip().lower()
        if key and key not in {x.lower() for x in merged_direct_match}:
            merged_direct_match.append(item.strip())

    return {
        "tool_name": tool_name,
        "module": module_name,
        "description": _tool_description(tool),
        "intent_aliases": merged_intent_aliases,
        "keywords": merged_keywords,
        "direct_match": merged_direct_match,
        "route": (tool_route or module_route or "reason").strip().lower(),
    }


def load_skills() -> List[Dict[str, Any]]:
    """Discover and import all skill modules in the skills/ directory."""
    global _loaded_skills
    _loaded_skills.clear()

    enabled_map: Dict[str, bool] = {}
    if CONFIG_PATH.exists():
        try:
            enabled_map = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("enabled", {})
            if not isinstance(enabled_map, dict):
                enabled_map = {}
        except Exception as e:
            print(f"[SKILLS] Config error: {e}")

    skip = {"__init__", "loader"}
    seen_tool_names = set()

    for path in sorted(SKILLS_DIR.glob("*.py")):
        name = path.stem
        if name in skip or name.startswith("_"):
            continue

        if not enabled_map.get(name, True):
            print(f"[SKILLS] Skipping disabled skill: {name}")
            continue

        module_name = f"skills.{name}"

        try:
            if module_name in sys.modules:
                mod = importlib.reload(sys.modules[module_name])
            else:
                mod = importlib.import_module(module_name)

            skill_name = getattr(mod, "SKILL_NAME", name)
            description = getattr(mod, "SKILL_DESCRIPTION", "")

            tools = getattr(mod, "TOOLS", [])
            if not isinstance(tools, list):
                tools = []

            tool_map = getattr(mod, "TOOL_MAP", {})
            if not isinstance(tool_map, dict):
                tool_map = {}

            keywords = getattr(mod, "KEYWORDS", {})
            if not isinstance(keywords, dict):
                keywords = {}

            skill_meta = getattr(mod, "SKILL_META", {})
            if not isinstance(skill_meta, dict):
                skill_meta = {}

            init_fn = getattr(mod, "init", None)
            if callable(init_fn):
                init_fn()

            validated_tools: List[Dict[str, Any]] = []
            validated_tool_map: Dict[str, Any] = {}
            validated_keywords: Dict[str, List[str]] = {}
            validated_skill_meta: Dict[str, Dict[str, Any]] = {}

            for tool in tools:
                if not isinstance(tool, dict):
                    continue

                tool_name = _tool_name(tool)
                if not tool_name:
                    print(f"[SKILLS] Warning: {skill_name} has a tool without function.name, skipping")
                    continue

                if tool_name in seen_tool_names:
                    print(f"[SKILLS] Warning: duplicate tool '{tool_name}' from {skill_name}, skipping")
                    continue

                executor = tool_map.get(tool_name)
                if not callable(executor):
                    print(f"[SKILLS] Warning: tool '{tool_name}' in {skill_name} has no callable executor, skipping")
                    continue

                tool_keywords = keywords.get(tool_name, [])
                if not isinstance(tool_keywords, list):
                    tool_keywords = []

                normalized_keywords = _fallback_keywords(tool_name, tool, tool_keywords)
                meta = _build_tool_meta(name, tool, normalized_keywords, skill_meta)

                validated_tools.append(tool)
                validated_tool_map[tool_name] = executor
                validated_keywords[tool_name] = normalized_keywords

                if meta:
                    validated_skill_meta[tool_name] = meta

                seen_tool_names.add(tool_name)

            _loaded_skills.append(
                {
                    "name": str(skill_name),
                    "description": str(description or ""),
                    "module": mod,
                    "tools": validated_tools,
                    "tool_map": validated_tool_map,
                    "keywords": validated_keywords,
                    "skill_meta": validated_skill_meta,
                }
            )

            tool_names = [t["function"]["name"] for t in validated_tools]
            print(f"[SKILLS] Loaded: {skill_name} — {len(validated_tools)} tools ({', '.join(tool_names)})")

        except Exception as e:
            print(f"[SKILLS] Failed to load {name}: {e}")

    print(f"[SKILLS] Total: {len(_loaded_skills)} skills, {len(get_all_tools())} tools")
    return _loaded_skills


def get_all_tools() -> List[Dict[str, Any]]:
    """Return merged TOOLS list from all loaded skills."""
    tools: List[Dict[str, Any]] = []
    for skill in _loaded_skills:
        tools.extend(skill["tools"])
    return tools


def get_all_tool_map() -> Dict[str, Any]:
    """Return merged {tool_name: executor} dict from all loaded skills."""
    merged: Dict[str, Any] = {}
    for skill in _loaded_skills:
        merged.update(skill["tool_map"])
    return merged


def get_all_keywords() -> Dict[str, List[str]]:
    """Return merged {tool_name: [keywords]} dict from all loaded skills."""
    merged: Dict[str, List[str]] = {}
    for skill in _loaded_skills:
        merged.update(skill["keywords"])
    return merged


def get_all_skill_meta() -> Dict[str, Dict[str, Any]]:
    """Return merged {tool_name: metadata} dict from all loaded skills."""
    merged: Dict[str, Dict[str, Any]] = {}
    for skill in _loaded_skills:
        merged.update(skill.get("skill_meta", {}))
    return merged


def get_loaded_skills() -> List[Dict[str, Any]]:
    """Return list of loaded skill info dicts."""
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "tools": [t["function"]["name"] for t in s["tools"]],
        }
        for s in _loaded_skills
    ]