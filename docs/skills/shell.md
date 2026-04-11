# Shell Skill

Execute shell commands (with safety filter) and read source code files.

**File:** `skills/shell.py`

---

## Tools

### shell_command

Run a shell command and return the output.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | yes | Shell command to execute |

**Timeout:** 30 seconds. Output capped at 4000 characters.

**Safety blocklist** — these patterns are blocked:
- `rm -rf`, `mkfs`, `dd if`, `format X:`, `del /s`, `shutdown`, `reboot`, `passwd`, `sudo rm`

**Examples:**
```
"Check disk space"           → shell_command("df -h")
"What's my IP?"              → shell_command("hostname -I")
"Git status of jarvis-os"    → shell_command("git -C /mnt/e/coding/jarvis-os status")
"List running processes"     → shell_command("ps aux | head -20")
```

---

### read_file

Read a source code file from allowed directories.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute file path |

Returns up to 8000 characters. Only allows reading from:
- `D:/Jarvis_vault` / `/mnt/d/Jarvis_vault`
- `E:/coding` / `/mnt/e/coding`

**Examples:**
```
"Show me the watcher script"  → read_file("/mnt/e/coding/jarvis-os/scripts/watcher.sh")
"Read the bridge module"      → read_file("/mnt/e/coding/jarvis-os/app/lib/bridge.ts")
```
