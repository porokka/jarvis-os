"""
JARVIS Skill — Claude Code skills browser (list and load vault skills).
"""

from pathlib import Path
import os

SKILL_NAME = "claude_skills"
SKILL_DESCRIPTION = "Browse and load Claude Code skills from the vault"

VAULT_DIR = Path("D:/Jarvis_vault") if os.name == "nt" else Path("/mnt/d/Jarvis_vault")
SKILLS_DIR = VAULT_DIR / ".claude" / "skills"


def exec_list_skills() -> str:
    if not SKILLS_DIR.exists():
        return "No skills directory found."

    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            content = (d / "SKILL.md").read_text(encoding="utf-8")
            desc = ""
            for line in content.split("\n"):
                if line.startswith("description:"):
                    desc = line.replace("description:", "").strip()[:100]
                    break
            skills.append(f"  {d.name} — {desc}")

    return "Available skills:\n" + "\n".join(skills) if skills else "No skills found."


def exec_use_skill(name: str) -> str:
    skill_path = SKILLS_DIR / name / "SKILL.md"
    if not skill_path.exists():
        if SKILLS_DIR.exists():
            matches = [d.name for d in SKILLS_DIR.iterdir() if name.lower() in d.name.lower()]
            if matches:
                return f"Skill '{name}' not found. Did you mean: {', '.join(matches)}?"
        return f"Skill '{name}' not found. Use list_skills to see available skills."

    try:
        return skill_path.read_text(encoding="utf-8")[:12000]
    except Exception as e:
        return f"Error loading skill: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List all available JARVIS skills (frontend-design, SEO, playwright, etc).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": "Load and apply a skill by name. Returns the full skill instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name, e.g. frontend-design"
                    }
                },
                "required": ["name"],
            },
        },
    },
]

TOOL_MAP = {
    "list_skills": exec_list_skills,
    "use_skill": exec_use_skill,
}

KEYWORDS = {
    "list_skills": [
        "skills",
        "what skills",
        "available skills",
        "what can you do",
        "capabilities",
        "list skills",
        "show skills",
    ],
    "use_skill": [
        "use skill",
        "apply skill",
        "load skill",
        "frontend",
        "seo",
        "playwright",
        "use frontend skill",
    ],
}

SKILL_META = {
    "intent_aliases": [
        "skills",
        "skill",
        "capabilities",
        "claude skills",
        "jarvis skills",
    ],
    "keywords": [
        "skills",
        "available skills",
        "list skills",
        "show skills",
        "what skills do you have",
        "what can you do",
        "capabilities",
        "use skill",
        "apply skill",
        "load skill",
    ],
    "route": "reason",
    "tools": {
        "list_skills": {
            "intent_aliases": [
                "list skills",
                "show skills",
                "available skills",
                "what skills",
                "capabilities",
            ],
            "keywords": [
                "list skills",
                "show skills",
                "available skills",
                "what skills do you have",
                "capabilities",
            ],
            "direct_match": [
                "list skills",
                "show skills",
                "available skills",
                "what skills do you have",
            ],
            "route": "reason",
        },
        "use_skill": {
            "intent_aliases": [
                "use skill",
                "apply skill",
                "load skill",
            ],
            "keywords": [
                "use skill",
                "apply skill",
                "load skill",
                "frontend",
                "seo",
                "playwright",
            ],
            "direct_match": [
                "use skill",
                "apply skill",
                "load skill",
            ],
            "route": "reason",
        },
    },
}