"""
Dynamic skill loader — discovers and imports all skill modules.

Usage:
    from skills import load_skills, get_all_tools, get_all_tool_map, get_all_keywords

    load_skills()           # import all enabled skills
    get_all_tools()         # merged TOOLS list for Ollama
    get_all_tool_map()      # merged {name: executor} dict
    get_all_keywords()      # merged {tool_name: [keywords]} dict
"""

import importlib
import json
from pathlib import Path

SKILLS_DIR = Path(__file__).parent
CONFIG_PATH = SKILLS_DIR.parent / "config" / "skills.json"

# Registry — populated by load_skills()
_loaded_skills = []


def load_skills():
    """Discover and import all skill modules in the skills/ directory."""
    global _loaded_skills
    _loaded_skills.clear()

    # Load enabled/disabled config
    enabled_map = {}
    if CONFIG_PATH.exists():
        try:
            enabled_map = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("enabled", {})
        except Exception as e:
            print(f"[SKILLS] Config error: {e}")

    skip = {"__init__", "loader"}

    for path in sorted(SKILLS_DIR.glob("*.py")):
        name = path.stem
        if name in skip or name.startswith("_"):
            continue

        # Check config — default to enabled if not listed
        if not enabled_map.get(name, True):
            print(f"[SKILLS] Skipping disabled skill: {name}")
            continue

        try:
            mod = importlib.import_module(f"skills.{name}")

            # Validate required attributes
            skill_name = getattr(mod, "SKILL_NAME", name)
            tools = getattr(mod, "TOOLS", [])
            tool_map = getattr(mod, "TOOL_MAP", {})
            keywords = getattr(mod, "KEYWORDS", {})
            description = getattr(mod, "SKILL_DESCRIPTION", "")

            # Call init hook if the skill has one
            init_fn = getattr(mod, "init", None)
            if callable(init_fn):
                init_fn()

            _loaded_skills.append({
                "name": skill_name,
                "description": description,
                "module": mod,
                "tools": tools,
                "tool_map": tool_map,
                "keywords": keywords,
            })

            tool_names = [t["function"]["name"] for t in tools]
            print(f"[SKILLS] Loaded: {skill_name} — {len(tools)} tools ({', '.join(tool_names)})")

        except Exception as e:
            print(f"[SKILLS] Failed to load {name}: {e}")

    print(f"[SKILLS] Total: {len(_loaded_skills)} skills, {len(get_all_tools())} tools")
    return _loaded_skills


def get_all_tools() -> list:
    """Return merged TOOLS list from all loaded skills."""
    tools = []
    for skill in _loaded_skills:
        tools.extend(skill["tools"])
    return tools


def get_all_tool_map() -> dict:
    """Return merged {tool_name: executor} dict from all loaded skills."""
    merged = {}
    for skill in _loaded_skills:
        merged.update(skill["tool_map"])
    return merged


def get_all_keywords() -> dict:
    """Return merged {tool_name: [keywords]} dict from all loaded skills."""
    merged = {}
    for skill in _loaded_skills:
        merged.update(skill["keywords"])
    return merged


def get_loaded_skills() -> list:
    """Return list of loaded skill info dicts."""
    return [
        {"name": s["name"], "description": s["description"],
         "tools": [t["function"]["name"] for t in s["tools"]]}
        for s in _loaded_skills
    ]
