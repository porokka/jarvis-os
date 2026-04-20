"""
JARVIS Skill — Project operations and controlled dependency installation.

Purpose:
  - Detect likely missing Python/Node dependencies
  - Install dependencies in approved project roots
  - Ask for permission before privileged actions
  - Optionally remember granted access per project

Config files:
  - config/project_ops.json
  - config/project_ops_access.json
"""

import json
import os
import re
import ast
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


SKILL_NAME = "project_ops"
SKILL_DESCRIPTION = "Controlled project installs, dependency checks, and remembered per-project access"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "developer"
SKILL_TAGS = ["python", "node", "npm", "pip", "dependencies", "install", "permissions"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "check_python_imports",
    "check_node_deps",
    "install_python_package",
    "install_node_package",
    "install_requirements",
    "install_package_json",
    "grant_access",
    "revoke_access",
    "access_status",
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
    "entrypoint": "exec_project_ops",
    "config_file": "config/project_ops.json",
    "access_file": "config/project_ops_access.json",
}

CONFIG_FILE = Path(__file__).parent.parent / "config" / "project_ops.json"
ACCESS_FILE = Path(__file__).parent.parent / "config" / "project_ops_access.json"

DEFAULT_ALLOWED_ROOTS = [
    str(Path("/mnt/e/coding").resolve()),
    str(Path("/mnt/d/Jarvis_vault").resolve()),
    str(Path("E:/coding").resolve()),
    str(Path("D:/Jarvis_vault").resolve()),
]

STDLIB_MODULES = {
    "os", "sys", "re", "json", "time", "datetime", "math", "pathlib", "subprocess",
    "typing", "collections", "itertools", "functools", "shlex", "tempfile", "shutil",
    "socket", "threading", "asyncio", "logging", "unittest", "traceback", "hashlib",
    "base64", "urllib", "http", "email", "sqlite3", "csv", "gzip", "zipfile",
    "tarfile", "argparse", "inspect", "enum", "dataclasses", "statistics", "random",
    "glob", "copy", "pprint", "signal", "platform", "io", "ast", "types", "queue",
    "multiprocessing", "contextlib", "fractions", "decimal", "configparser", "string",
    "secrets", "ssl", "xml", "html",
}


def _load_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_config() -> dict:
    cfg = _load_json(CONFIG_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    roots = cfg.get("allowed_roots", DEFAULT_ALLOWED_ROOTS)
    if not isinstance(roots, list):
        roots = DEFAULT_ALLOWED_ROOTS
    return {
        "allowed_roots": roots,
        "default_python": cfg.get("default_python", "python"),
        "default_node_pm": cfg.get("default_node_pm", "npm"),
    }


def _load_access() -> dict:
    data = _load_json(ACCESS_FILE, {"projects": {}})
    if not isinstance(data, dict):
        data = {"projects": {}}
    if "projects" not in data or not isinstance(data["projects"], dict):
        data["projects"] = {}
    return data


def _save_access(data: dict) -> None:
    _save_json(ACCESS_FILE, data)


def _allowed_roots() -> List[Path]:
    cfg = _load_config()
    out = []
    for root in cfg["allowed_roots"]:
        try:
            out.append(Path(root).resolve())
        except Exception:
            pass
    return out


def _resolve_project(project_path: str) -> Tuple[Optional[Path], Optional[str]]:
    if not project_path or not project_path.strip():
        return None, "Error: project path is required"

    try:
        p = Path(project_path).resolve()
    except Exception as e:
        return None, f"Error: invalid project path: {e}"

    for root in _allowed_roots():
        try:
            p.relative_to(root)
            return p, None
        except ValueError:
            continue

    return None, "Error: project path is outside allowed roots"


def _project_key(project_path: Path) -> str:
    return str(project_path.resolve()).replace("\\", "/")


def _has_saved_access(project_path: Path) -> bool:
    data = _load_access()
    return bool(data["projects"].get(_project_key(project_path), {}).get("granted"))


def _grant_access(project_path: Path, remember: bool = True) -> str:
    if not remember:
        return f"Access granted for this run only: {_project_key(project_path)}"

    data = _load_access()
    data["projects"][_project_key(project_path)] = {
        "granted": True,
    }
    _save_access(data)
    return f"Access granted and saved: {_project_key(project_path)}"


def _revoke_access(project_path: Path) -> str:
    data = _load_access()
    key = _project_key(project_path)
    if key in data["projects"]:
        del data["projects"][key]
        _save_access(data)
        return f"Access revoked: {key}"
    return f"No saved access found for: {key}"


def _require_access(project_path: Path) -> Optional[str]:
    if _has_saved_access(project_path):
        return None
    return (
        f"Access required for privileged install action in:\n{_project_key(project_path)}\n"
        f"Run grant_access for this project first, optionally with remember=true."
    )


def _run(cmd: List[str], cwd: Path, timeout: int = 240) -> str:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        out = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        prefix = f"[exit {result.returncode}] {' '.join(cmd)}\n"
        text = prefix + (out or "(no output)")
        return text[:8000]
    except subprocess.TimeoutExpired:
        return f"Error: command timed out ({timeout}s)"
    except FileNotFoundError:
        return f"Error: command not found: {cmd[0]}"
    except Exception as e:
        return f"Error: {e}"


def _safe_pkg_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._@/\-]+", (name or "").strip()))


def _find_python_files(project_path: Path) -> List[Path]:
    out = []
    for p in project_path.rglob("*.py"):
        parts = {x.lower() for x in p.parts}
        if any(x in parts for x in {".venv", "venv", "__pycache__", "node_modules", ".git"}):
            continue
        out.append(p)
    return out[:500]


def _parse_python_imports(py_file: Path) -> List[str]:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return []

    imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root:
                    imports.add(root)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                root = node.module.split(".")[0]
                if root:
                    imports.add(root)

    return sorted(imports)


def _detect_missing_python_imports(project_path: Path, python_bin: str) -> str:
    files = _find_python_files(project_path)
    if not files:
        return "No Python files found."

    found = set()
    for f in files:
        found.update(_parse_python_imports(f))

    filtered = sorted(x for x in found if x and x not in STDLIB_MODULES)

    if not filtered:
        return "No non-stdlib imports detected."

    missing = []
    present = []

    for mod in filtered:
        code = f"import importlib.util; print('OK' if importlib.util.find_spec('{mod}') else 'MISSING')"
        result = _run([python_bin, "-c", code], cwd=project_path, timeout=30)
        if "OK" in result:
            present.append(mod)
        else:
            missing.append(mod)

    lines = [
        f"Python import scan in {project_path}",
        f"Detected non-stdlib imports: {len(filtered)}",
        f"Present: {', '.join(present) if present else '(none)'}",
        f"Missing: {', '.join(missing) if missing else '(none)'}",
    ]
    if missing:
        lines.append("You can install one with action=install_python_package or bulk install from requirements.txt.")
    return "\n".join(lines)


def _check_node_deps(project_path: Path) -> str:
    package_json = project_path / "package.json"
    if not package_json.exists():
        return "No package.json found."

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Error reading package.json: {e}"

    deps = data.get("dependencies", {}) or {}
    dev_deps = data.get("devDependencies", {}) or {}
    all_deps = {**deps, **dev_deps}

    if not all_deps:
        return "package.json has no dependencies or devDependencies."

    node_modules = project_path / "node_modules"
    if not node_modules.exists():
        return (
            f"package.json contains {len(all_deps)} dependencies, but node_modules is missing.\n"
            f"Run install_package_json after access is granted."
        )

    missing = []
    for pkg in all_deps.keys():
        if pkg.startswith("@"):
            scope, name = pkg.split("/", 1)
            pkg_path = node_modules / scope / name
        else:
            pkg_path = node_modules / pkg

        if not pkg_path.exists():
            missing.append(pkg)

    if missing:
        return (
            f"Node dependency check in {project_path}\n"
            f"Declared: {len(all_deps)}\n"
            f"Missing in node_modules: {', '.join(missing[:50])}"
        )

    return f"Node dependency check in {project_path}\nDeclared: {len(all_deps)}\nAll declared packages appear present."


def _install_python_package(project_path: Path, package: str, python_bin: str) -> str:
    if not _safe_pkg_name(package):
        return "Error: invalid package name"
    return _run([python_bin, "-m", "pip", "install", package], cwd=project_path, timeout=600)


def _install_requirements(project_path: Path, python_bin: str) -> str:
    req = project_path / "requirements.txt"
    if not req.exists():
        return "Error: requirements.txt not found"
    return _run([python_bin, "-m", "pip", "install", "-r", "requirements.txt"], cwd=project_path, timeout=1200)


def _install_node_package(project_path: Path, package: str, dev: bool, pm: str) -> str:
    if not _safe_pkg_name(package):
        return "Error: invalid package name"

    if pm not in {"npm", "pnpm", "yarn"}:
        return "Error: package manager must be npm, pnpm, or yarn"

    if pm == "npm":
        cmd = ["npm", "install", package]
        if dev:
            cmd.append("--save-dev")
    elif pm == "pnpm":
        cmd = ["pnpm", "add", package]
        if dev:
            cmd.append("-D")
    else:
        cmd = ["yarn", "add", package]
        if dev:
            cmd.append("-D")

    return _run(cmd, cwd=project_path, timeout=1200)


def _install_package_json(project_path: Path, pm: str) -> str:
    if pm not in {"npm", "pnpm", "yarn"}:
        return "Error: package manager must be npm, pnpm, or yarn"

    package_json = project_path / "package.json"
    if not package_json.exists():
        return "Error: package.json not found"

    cmd = {
        "npm": ["npm", "install"],
        "pnpm": ["pnpm", "install"],
        "yarn": ["yarn", "install"],
    }[pm]

    return _run(cmd, cwd=project_path, timeout=1800)


def exec_project_ops(
    action: str,
    project_path: str = "",
    package: str = "",
    remember: bool = False,
    dev: bool = False,
    package_manager: str = "",
    python_bin: str = "",
) -> str:
    action = (action or "").strip().lower()
    cfg = _load_config()
    pm = (package_manager or cfg["default_node_pm"] or "npm").strip().lower()
    py = (python_bin or cfg["default_python"] or "python").strip()

    if action == "access_status":
        project, err = _resolve_project(project_path)
        if err:
            return err
        return (
            f"Project: {_project_key(project)}\n"
            f"Saved access: {'yes' if _has_saved_access(project) else 'no'}"
        )

    if action == "grant_access":
        project, err = _resolve_project(project_path)
        if err:
            return err
        return _grant_access(project, remember=remember)

    if action == "revoke_access":
        project, err = _resolve_project(project_path)
        if err:
            return err
        return _revoke_access(project)

    if action == "check_python_imports":
        project, err = _resolve_project(project_path)
        if err:
            return err
        return _detect_missing_python_imports(project, python_bin=py)

    if action == "check_node_deps":
        project, err = _resolve_project(project_path)
        if err:
            return err
        return _check_node_deps(project)

    if action in {
        "install_python_package",
        "install_node_package",
        "install_requirements",
        "install_package_json",
    }:
        project, err = _resolve_project(project_path)
        if err:
            return err

        access_err = _require_access(project)
        if access_err:
            return access_err

        if action == "install_python_package":
            if not package:
                return "Error: package is required"
            return _install_python_package(project, package=package, python_bin=py)

        if action == "install_node_package":
            if not package:
                return "Error: package is required"
            return _install_node_package(project, package=package, dev=dev, pm=pm)

        if action == "install_requirements":
            return _install_requirements(project, python_bin=py)

        if action == "install_package_json":
            return _install_package_json(project, pm=pm)

    return (
        "Available actions: "
        "check_python_imports, check_node_deps, "
        "install_python_package, install_node_package, install_requirements, install_package_json, "
        "grant_access, revoke_access, access_status"
    )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "project_ops",
            "description": (
                "Controlled dependency checks and installs for approved project directories. "
                "Can remember per-project access before privileged install actions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "check_python_imports",
                            "check_node_deps",
                            "install_python_package",
                            "install_node_package",
                            "install_requirements",
                            "install_package_json",
                            "grant_access",
                            "revoke_access",
                            "access_status",
                        ],
                        "description": "Project operation to perform.",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Absolute project path inside an approved root.",
                    },
                    "package": {
                        "type": "string",
                        "description": "Single package name for install_python_package or install_node_package.",
                    },
                    "remember": {
                        "type": "boolean",
                        "description": "When granting access, save permission for this project.",
                    },
                    "dev": {
                        "type": "boolean",
                        "description": "Install Node package as dev dependency.",
                    },
                    "package_manager": {
                        "type": "string",
                        "enum": ["npm", "pnpm", "yarn"],
                        "description": "Node package manager.",
                    },
                    "python_bin": {
                        "type": "string",
                        "description": "Python executable name, e.g. python, python3, py.",
                    },
                },
                "required": ["action", "project_path"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "project_ops": exec_project_ops,
}

KEYWORDS = {
    "project_ops": [
        "install dependency",
        "install package",
        "missing library",
        "missing package",
        "pip install",
        "npm install",
        "pnpm install",
        "requirements.txt",
        "package.json",
        "grant access",
        "save access",
        "revoke access",
        "project setup",
    ],
}

SKILL_EXAMPLES = [
    {
        "command": "check missing python imports",
        "tool": "project_ops",
        "args": {
            "action": "check_python_imports",
            "project_path": "/mnt/e/coding/myproj",
        },
    },
    {
        "command": "grant saved access to this project",
        "tool": "project_ops",
        "args": {
            "action": "grant_access",
            "project_path": "/mnt/e/coding/myproj",
            "remember": True,
        },
    },
    {
        "command": "install requests",
        "tool": "project_ops",
        "args": {
            "action": "install_python_package",
            "project_path": "/mnt/e/coding/myproj",
            "package": "requests",
        },
    },
    {
        "command": "install package.json deps",
        "tool": "project_ops",
        "args": {
            "action": "install_package_json",
            "project_path": "/mnt/e/coding/myproj",
            "package_manager": "npm",
        },
    },
]