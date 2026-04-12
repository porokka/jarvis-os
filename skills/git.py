"""
JARVIS Skill — Git repository management.

Provides dedicated git tools for common operations.
Works on any repo under the allowed read roots.
"""

import subprocess
import re
from pathlib import Path

SKILL_NAME = "git"
SKILL_DESCRIPTION = "Git — status, diff, commit, log, push, pull, branches"

ALLOWED_ROOTS = [
    "/mnt/e/coding",
    "/mnt/d/Jarvis_vault",
    "E:/coding",
    "D:/Jarvis_vault",
]


def _git(repo: str, *args: str, timeout: int = 30) -> str:
    """Run a git command in a repo directory."""
    # Resolve repo path
    repo_path = Path(repo).resolve()
    if not any(str(repo_path).startswith(root) for root in ALLOWED_ROOTS):
        return f"Error: repo path not in allowed roots"
    if not (repo_path / ".git").exists() and not repo_path.name == ".git":
        # Try as project name under /mnt/e/coding
        for root in ["/mnt/e/coding", "E:/coding"]:
            candidate = Path(root) / repo
            if (candidate / ".git").exists():
                repo_path = candidate
                break
        else:
            return f"Error: not a git repo: {repo}"

    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(repo_path),
            capture_output=True, text=True, timeout=timeout,
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
    # Add last commit info
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
    return _git(repo, "log", f"--oneline", f"-{n}", "--decorate")


def exec_git_commit(repo: str, message: str, files: str = ".") -> str:
    """Stage files and commit."""
    if not message:
        return "Error: commit message required"

    # Stage
    file_list = [f.strip() for f in files.split(",")]
    for f in file_list:
        result = _git(repo, "add", f)
        if "Error" in result:
            return result

    # Check if anything to commit
    status = _git(repo, "status", "--porcelain")
    if not status or status == "(no output)":
        return "Nothing to commit — working tree clean."

    # Commit
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
        return _git(repo, "checkout", "-b", name)
    elif action.startswith("switch "):
        name = action[7:].strip()
        return _git(repo, "checkout", name)
    else:
        return f"Unknown branch action. Use: list, create <name>, switch <name>"


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
    elif action == "branch" or action == "branches":
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
    else:
        return (
            f"Unknown git action '{action}'. Available: "
            "status, diff, log, commit, push, pull, branch, stash, stash_pop, blame"
        )


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "git",
            "description": "Git repository management. Actions: status, diff, log, commit, push, pull, branch (list/create/switch), stash, stash_pop, blame. Repo can be a full path or project name (e.g. 'jarvis-os').",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository path or project name (e.g. 'jarvis-os', 'stockwatch-app', '/mnt/e/coding/jarvis-os')",
                    },
                    "action": {
                        "type": "string",
                        "description": "Action: status, diff, log, commit, push, pull, branch, stash, stash_pop, blame",
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
        "git", "commit", "push", "pull", "branch", "diff", "status",
        "repository", "repo", "changes", "merge", "stash", "blame",
    ],
}
