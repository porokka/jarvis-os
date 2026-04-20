"""
JARVIS Skill — Git repository management.

Provides dedicated git tools for common operations.
Works on any repo under the allowed roots.
"""

import subprocess
from pathlib import Path

SKILL_NAME = "git"
SKILL_DESCRIPTION = "Git — status, diff, commit, log, push, pull, branches, ignore"

ALLOWED_ROOTS = [
    "/mnt/e/coding",
    "/mnt/d/Jarvis_vault",
    "E:/coding",
    "D:/Jarvis_vault",
]


def _resolve_repo(repo: str) -> Path | None:
    """Resolve repo path from full path or project name."""
    repo_path = Path(repo).resolve()

    if any(str(repo_path).startswith(root) for root in ALLOWED_ROOTS) and (repo_path / ".git").exists():
        return repo_path

    # Try as project name under common roots
    for root in ["/mnt/e/coding", "E:/coding", "/mnt/d/Jarvis_vault", "D:/Jarvis_vault"]:
        candidate = Path(root) / repo
        if (candidate / ".git").exists():
            return candidate.resolve()

    # Allow passing .git dir itself
    if any(str(repo_path).startswith(root) for root in ALLOWED_ROOTS) and repo_path.name == ".git":
        return repo_path.parent.resolve()

    return None


def _git(repo: str, *args: str, timeout: int = 30) -> str:
    """Run a git command in a repo directory."""
    repo_path = _resolve_repo(repo)
    if repo_path is None:
        return f"Error: not a git repo or not in allowed roots: {repo}"

    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:4000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: git command timed out"
    except Exception as e:
        return f"Error: {e}"


def exec_git_status(repo: str) -> str:
    """Show git status of a repository."""
    status = _git(repo, "status", "--short", "--branch")
    last = _git(repo, "log", "--oneline", "-1")
    return f"{status}\n\nLast commit: {last}"


def exec_git_diff(repo: str, file: str = "") -> str:
    """Show git diff (staged + unstaged changes)."""
    if file:
        diff = _git(repo, "diff", "--", file)
        staged = _git(repo, "diff", "--cached", "--", file)
    else:
        diff = _git(repo, "diff")
        staged = _git(repo, "diff", "--cached")

    parts = []
    if staged and staged != "(no output)":
        parts.append(f"=== STAGED ===\n{staged}")
    if diff and diff != "(no output)":
        parts.append(f"=== UNSTAGED ===\n{diff}")

    return "\n\n".join(parts) if parts else "No changes."


def exec_git_log(repo: str, count: str = "10") -> str:
    """Show recent git log."""
    n = min(int(count), 50) if count.isdigit() else 10
    return _git(repo, "log", "--oneline", f"-{n}", "--decorate")


def exec_git_commit(repo: str, message: str, files: str = ".") -> str:
    """Stage files and commit."""
    if not message:
        return "Error: commit message required"

    file_list = [f.strip() for f in files.split(",") if f.strip()]
    if not file_list:
        file_list = ["."]

    for f in file_list:
        result = _git(repo, "add", f)
        if "Error" in result:
            return result

    status = _git(repo, "status", "--porcelain")
    if not status or status == "(no output)":
        return "Nothing to commit — working tree clean."

    return _git(repo, "commit", "-m", message)


def exec_git_push(repo: str, remote: str = "origin", branch: str = "") -> str:
    """Push to remote."""
    if branch:
        return _git(repo, "push", remote, branch, timeout=60)
    return _git(repo, "push", timeout=60)


def exec_git_pull(repo: str) -> str:
    """Pull from remote."""
    return _git(repo, "pull", timeout=60)


def exec_git_branch(repo: str, action: str = "list") -> str:
    """List, create, or switch branches."""
    if action == "list":
        return _git(repo, "branch", "-a", "--no-color")
    elif action.startswith("create "):
        name = action[7:].strip()
        if not name:
            return "Error: branch name required"
        return _git(repo, "checkout", "-b", name)
    elif action.startswith("switch "):
        name = action[7:].strip()
        if not name:
            return "Error: branch name required"
        return _git(repo, "checkout", name)
    else:
        return "Unknown branch action. Use: list, create <name>, switch <name>"


def exec_git_ignore(repo: str, pattern: str) -> str:
    """Add a pattern to .gitignore safely."""
    if not pattern or not pattern.strip():
        return "Error: pattern required"

    repo_path = _resolve_repo(repo)
    if repo_path is None:
        return f"Error: not a git repo or not in allowed roots: {repo}"

    gitignore = repo_path / ".gitignore"
    normalized = pattern.strip()

    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        existing_lines = [line.strip() for line in existing.splitlines()]

        if normalized in existing_lines:
            return f"Pattern already exists in .gitignore: {normalized}"

        with open(gitignore, "a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(normalized + "\n")

        return f"Added to .gitignore: {normalized}"
    except Exception as e:
        return f"Error updating .gitignore: {e}"


def exec_git(repo: str, action: str, **kwargs) -> str:
    """Main git dispatcher."""
    action = action.lower().strip()

    if action == "status":
        return exec_git_status(repo)
    elif action == "diff":
        return exec_git_diff(repo, kwargs.get("file", ""))
    elif action == "log":
        return exec_git_log(repo, kwargs.get("count", "10"))
    elif action == "commit":
        return exec_git_commit(repo, kwargs.get("message", ""), kwargs.get("files", "."))
    elif action == "push":
        return exec_git_push(repo, kwargs.get("remote", "origin"), kwargs.get("branch", ""))
    elif action == "pull":
        return exec_git_pull(repo)
    elif action in ("branch", "branches"):
        return exec_git_branch(repo, kwargs.get("branch_action", "list"))
    elif action == "stash":
        return _git(repo, "stash")
    elif action == "stash_pop":
        return _git(repo, "stash", "pop")
    elif action == "blame":
        f = kwargs.get("file", "")
        if not f:
            return "Error: file required for blame"
        return _git(repo, "blame", "--date=short", f)
    elif action == "ignore":
        return exec_git_ignore(repo, kwargs.get("pattern", ""))
    else:
        return (
            f"Unknown git action '{action}'. Available: "
            "status, diff, log, commit, push, pull, branch, stash, stash_pop, blame, ignore"
        )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "git",
            "description": "Git repository management. Actions: status, diff, log, commit, push, pull, branch (list/create/switch), stash, stash_pop, blame, ignore (.gitignore management). Repo can be a full path or project name such as 'jarvis-os'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository path or project name (e.g. 'jarvis-os', 'stockwatch-app', '/mnt/e/coding/jarvis-os')",
                    },
                    "action": {
                        "type": "string",
                        "description": "Action: status, diff, log, commit, push, pull, branch, stash, stash_pop, blame, ignore",
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message (for commit action)",
                    },
                    "files": {
                        "type": "string",
                        "description": "Files to stage, comma-separated (for commit action, default: '.')",
                    },
                    "file": {
                        "type": "string",
                        "description": "File path (for diff or blame)",
                    },
                    "count": {
                        "type": "string",
                        "description": "Number of log entries (default: 10)",
                    },
                    "branch_action": {
                        "type": "string",
                        "description": "Branch action: list, create <name>, switch <name>",
                    },
                    "remote": {
                        "type": "string",
                        "description": "Remote name for push (default: origin)",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch name for push",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Pattern to add to .gitignore (e.g. *.log, node_modules/, .env)",
                    },
                },
                "required": ["repo", "action"],
            },
        },
    },
]

TOOL_MAP = {
    "git": exec_git,
}

KEYWORDS = {
    "git": [
        "git",
        "commit",
        "push",
        "pull",
        "branch",
        "diff",
        "status",
        "repository",
        "repo",
        "changes",
        "stash",
        "blame",
        "gitignore",
        "ignore file",
        "ignore files",
        "exclude files",
    ],
}

SKILL_META = {
    "intent_aliases": [
        "git",
        "repo",
        "repository",
        "version control",
    ],
    "keywords": [
        "git",
        "git status",
        "git diff",
        "git log",
        "git commit",
        "git push",
        "git pull",
        "git branch",
        "gitignore",
        "ignore file",
        "ignore files",
        "repository",
        "repo",
        "stash",
        "blame",
    ],
    "route": "code",
    "tools": {
        "git": {
            "intent_aliases": [
                "git",
                "repo",
                "repository",
                "git status",
                "git diff",
                "git commit",
                "git push",
                "git pull",
                "gitignore",
            ],
            "keywords": [
                "git",
                "commit",
                "push",
                "pull",
                "branch",
                "diff",
                "status",
                "repository",
                "repo",
                "changes",
                "stash",
                "blame",
                "gitignore",
                "ignore file",
                "ignore files",
                "exclude files",
            ],
            "direct_match": [
                "git status",
                "git diff",
                "git log",
                "git commit",
                "git push",
                "git pull",
                "git branch",
                "git stash",
                "git blame",
                "gitignore",
                "ignore file",
                "ignore files",
                "add to gitignore",
            ],
            "route": "code",
        }
    },
}