# Git Skill

Git repository management via voice or text commands.

**File:** `skills/git.py`

---

## Tools

### git

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | yes | Project name or full path |
| `action` | string | yes | Git action |
| `message` | string | no | Commit message |
| `files` | string | no | Files to stage (comma-separated) |
| `file` | string | no | File for diff/blame |
| `count` | string | no | Log entries (default 10) |
| `branch_action` | string | no | list, create, switch |

**Actions:** `status`, `diff`, `log`, `commit`, `push`, `pull`, `branch`, `stash`, `stash_pop`, `blame`

**Examples:**
```
"Git status of jarvis-os"
"Show diff on stockwatch-app"
"Commit jarvis-os with message fix radio bug"
"Push jarvis-os"
"Git branches of jarvis-os"
```

Repo can be a name (`jarvis-os`) or full path (`/mnt/e/coding/jarvis-os`).
