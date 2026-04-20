"""
JARVIS Skill — System control for skill registry.

Allows Jarvis to list loaded skills and trigger skill reload.
"""

import json
import urllib.request


SKILL_NAME = "system_control"
SKILL_DESCRIPTION = "System control — list skills and reload skills"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "system"
SKILL_TAGS = ["system", "skills", "reload", "admin"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = ["list_skills", "reload_skills"]

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
    "reads_files": True,
    "network_access": True,
    "entrypoint": "exec_system_control",
    "route": "tools",
}

REACT_HOST = "http://127.0.0.1:7900"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def exec_system_control(action: str) -> str:
    action = (action or "").strip().lower()

    if action == "list_skills":
        try:
            data = _get_json(f"{REACT_HOST}/api/skills")
            skills = data.get("skills", [])
            tools = data.get("tools", [])

            lines = []
            lines.append(f"Loaded skills: {len(skills)}")
            for s in skills:
                lines.append(f"- {s}")
            lines.append("")
            lines.append(f"Tools: {len(tools)}")
            for t in tools:
                lines.append(f"- {t}")

            return "\n".join(lines)
        except Exception as e:
            return f"Error listing skills: {e}"

    if action == "reload_skills":
        try:
            data = _get_json(f"{REACT_HOST}/api/reload-skills")
            if data.get("status") == "ok":
                tools = data.get("tools", [])
                return f"Skills reloaded successfully. Loaded {data.get('tool_count', len(tools))} tools: {', '.join(tools)}"
            return f"Reload failed: {data}"
        except Exception as e:
            return f"Error reloading skills: {e}"

    return "Available actions: list_skills, reload_skills"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "system_control",
            "description": "List loaded skills or reload the Jarvis skill registry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_skills", "reload_skills"],
                        "description": "System action to perform.",
                    }
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "system_control": exec_system_control,
}

KEYWORDS = {
    "system_control": [
        "what skills",
        "list skills",
        "show skills",
        "reload skills",
        "refresh skills",
        "what can you do",
    ],
}

SKILL_EXAMPLES = [
    {"command": "what skills do you have", "tool": "system_control", "args": {"action": "list_skills"}},
    {"command": "reload skills", "tool": "system_control", "args": {"action": "reload_skills"}},
]