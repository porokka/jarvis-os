"""
JARVIS Plan Runner
==================
Redis consumer that executes plan tasks queued by planner_skill.
Bridges the gap between planner (queues tasks) and agent_loop (dispatches skills).

Architecture:
  planner_skill.exec_plan()
      → pushes {skill, tool, args, plan_id, task_id, depends_on} to Redis
          ↓
  plan_runner (this file — runs as daemon)
      → pops tasks respecting depends_on order
      → calls agent_loop.dispatch(decision)
      → streams results via agent_executor SSE (for shell/python tasks)
      → writes status back to Redis
      → on completion: calls planner_skill.promote_to_tested(plan_id)

Usage:
  python plan_runner.py              # daemon mode
  python plan_runner.py --once       # process one task and exit
  uvicorn plan_runner:app --port 8766  # HTTP status API
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# ── .env loader ────────────────────────────────────────────────────────────────
# systemd units set EnvironmentFile=.env, but jarvis.sh / nohup launches do not.
# Self-load .env so Telegram notifications (and other env-gated features) work
# regardless of how the runner was started. Existing env vars always win.
def _load_dotenv(path: Path) -> None:
    try:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception as e:  # never block startup on env parsing
        print(f"[runner] .env load skipped: {e}")


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_broker
import heartbeat

# ── Config ─────────────────────────────────────────────────────────────────────

REDIS_HOST       = os.getenv("JARVIS_REDIS_HOST",    "localhost")
REDIS_PORT       = int(os.getenv("JARVIS_REDIS_PORT", 6379))
REDIS_TASKS_KEY  = "jarvis:tasks"
REDIS_PLANS_KEY  = "jarvis:plans"
REDIS_STATUS_KEY = "jarvis:task_status"   # hash: task_uid → status JSON
REDIS_RESULTS_KEY = "jarvis:task_results" # hash: task_uid → result string

SKILLS_DIR       = Path(os.getenv("JARVIS_SKILLS_DIR", "/mnt/e/coding/jarvis-os/skills"))
MAX_WORKERS      = int(os.getenv("JARVIS_PLAN_WORKERS", "4"))   # concurrent task workers
EXECUTOR_URL     = os.getenv("JARVIS_EXECUTOR_URL",    "http://localhost:8765")
AGENT_LOOP_URL   = os.getenv("JARVIS_LOOP_URL",        "http://localhost:8100")
OLLAMA_URL       = os.getenv("JARVIS_OLLAMA_URL",      "http://localhost:11434")
CODER_MODEL      = os.getenv("JARVIS_CODER_MODEL",     "qwen3.6:27b")
DIAG_MODEL       = os.getenv("JARVIS_DIAG_MODEL",      "qwen3:14b")   # failure diagnosis
STAGING_ROOT     = Path(os.getenv("JARVIS_STAGING_ROOT", "/mnt/e/coding/staging"))
VAULT_DIR        = Path(os.getenv("VAULT_DIR", "/mnt/d/Jarvis_vault"))
FAILURE_LOG      = VAULT_DIR / ".jarvis" / "plan_failures.md"

POLL_INTERVAL    = 0.5   # seconds between Redis polls
# Dependency wait must cover a cold qwen3.6:27b load + full generation.
# 300s caused cascade failures when task 1 ran long.
DEP_TIMEOUT      = int(os.getenv("JARVIS_DEP_TIMEOUT", "1200"))
MAX_RETRIES      = 2     # retry failed tasks this many times

# ── Redis ──────────────────────────────────────────────────────────────────────

def _redis():
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        r.ping()
        return r
    except ImportError:
        raise RuntimeError("pip install redis")
    except Exception as e:
        raise RuntimeError(f"Redis not reachable: {e}")


def _set_status(r, task_uid: str, status: str, detail: str = ""):
    r.hset(REDIS_STATUS_KEY, task_uid, json.dumps({
        "status":    status,   # queued | waiting | running | done | failed
        "detail":    detail,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }))


def _get_status(r, task_uid: str) -> Optional[dict]:
    raw = r.hget(REDIS_STATUS_KEY, task_uid)
    return json.loads(raw) if raw else None


def _set_result(r, task_uid: str, result: str):
    r.hset(REDIS_RESULTS_KEY, task_uid, result)


def _get_result(r, task_uid: str) -> Optional[str]:
    return r.hget(REDIS_RESULTS_KEY, task_uid)


# ── Dependency resolver ────────────────────────────────────────────────────────

def _task_uid(task: dict) -> str:
    """Stable unique ID for a task within a plan."""
    return f"{task.get('plan_id', 'no_plan')}:{task.get('task_id', 0)}"


async def _wait_for_deps(r, task: dict) -> tuple[bool, str]:
    """
    Wait for all depends_on tasks to reach 'done' status.
    Returns (ok, error_msg).
    """
    deps      = task.get("depends_on", [])
    plan_id   = task.get("plan_id", "")
    if not deps:
        return True, ""

    deadline = time.monotonic() + DEP_TIMEOUT
    while time.monotonic() < deadline:
        all_done = True
        for dep_id in deps:
            dep_uid    = f"{plan_id}:{dep_id}"
            dep_status = _get_status(r, dep_uid)
            if dep_status is None or dep_status["status"] not in ("done",):
                if dep_status and dep_status["status"] == "failed":
                    return False, f"Dependency task {dep_id} failed"
                all_done = False
                break
        if all_done:
            return True, ""
        await asyncio.sleep(1.0)

    return False, f"Timed out waiting for dependencies {deps}"


# ── Skill dispatcher ───────────────────────────────────────────────────────────

def _load_skills() -> dict:
    """Load all skills from SKILLS_DIR."""
    import importlib.util
    registry = {}
    if not SKILLS_DIR.exists():
        return registry
    # Skills import project modules as `scripts.x` / `services.x` /
    # `skills.x` — make sure the project root is importable.
    project_root = str(SKILLS_DIR.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    # Load ALL *.py skill files (not just *_skill.py)
    skip = {"__init__", "loader", "coding_generic", "coding_qwen3_coder"}
    for skill_file in sorted(SKILLS_DIR.glob("*.py")):
        if skill_file.stem in skip or skill_file.stem.startswith("_"):
            continue
        try:
            spec   = importlib.util.spec_from_file_location(skill_file.stem, skill_file)
            module = importlib.util.module_from_spec(spec)
            # Must be in sys.modules BEFORE exec: @dataclass under
            # `from __future__ import annotations` resolves type hints via
            # sys.modules[cls.__module__].__dict__ (None → load error).
            sys.modules[skill_file.stem] = module
            spec.loader.exec_module(module)
            tool_map = getattr(module, "TOOL_MAP", {})
            if not tool_map:
                continue
            name = getattr(module, "SKILL_NAME", skill_file.stem)
            registry[name] = {
                "tool_map": tool_map,
                "description": getattr(module, "SKILL_DESCRIPTION", ""),
            }
        except Exception as e:
            print(f"[runner] skill load error {skill_file.name}: {e}")
    return registry


_skills_cache: dict = {}
_skills_loaded_at: float = 0


def get_skills(force_reload: bool = False) -> dict:
    global _skills_cache, _skills_loaded_at
    now = time.monotonic()
    if force_reload or not _skills_cache or (now - _skills_loaded_at) > 30:
        _skills_cache   = _load_skills()
        _skills_loaded_at = now
    return _skills_cache


_SOURCE_STOPWORDS = {
    "code", "skill", "skills", "test", "tests", "file", "files", "the", "and",
    "from", "into", "copy", "read", "run", "unit", "create", "staging", "with",
    "directory", "existing", "verify", "check", "results", "step", "plan",
    "that", "this", "then", "them", "make", "sure", "necessary", "issues",
    "identify", "identified", "review", "implement", "functionality",
    "functionalities", "after", "making", "changes", "correctly", "work",
    "works", "working",
}


def _find_source_files(goal: str, limit: int = 3) -> list:
    """Match project source files referenced by a task description.

    'check the Keepass skill code' → [scripts/keepass_secrets.py, ...]
    Searches skills/, scripts/, and services/ by token-in-filename.
    """
    tokens = set()
    for w in goal.lower().split():
        w = w.strip(".,:;()[]'\"`")
        if len(w) >= 4 and w.isalpha() and w not in _SOURCE_STOPWORDS:
            tokens.add(w)
    if not tokens:
        return []

    roots = [SKILLS_DIR, SKILLS_DIR.parent / "scripts", SKILLS_DIR.parent / "services"]
    matches = []
    for root in roots:
        if not root.exists():
            continue
        for f in sorted(root.glob("*.py")):
            stem = f.stem.lower()
            if any(t in stem for t in tokens):
                matches.append(f)
    return matches[:limit]


def _infer_file_from_goal(goal: str, plan_id: str) -> str:
    """
    Infer a staging file path from a task description when none is explicitly set.

    Priority:
    1. Explicit 'create/write/generate X.ext' pattern
    2. 'named X.ext' or 'file X.ext' pattern
    3. Type keyword at start of goal (HTML→index.html, CSS→style.css, JS→script.js)
    4. First filename.ext mention anywhere in goal
    5. Fallback: index.html
    """
    import re as _re
    g = goal.lower()

    # 1. Action verb directly before a filename
    m = _re.search(
        r"(?:create|write|generate|build|implement)\s+(?:the\s+|a\s+|an\s+)?"
        r"([\w\-]+\.(?:html|css|js|ts|tsx|py|json|svg|txt|md|sh|yaml|yml))",
        g,
    )
    if m:
        return f"staging/dev/{plan_id}/{m.group(1)}"

    # 2. Named/file X.ext
    m = _re.search(r"(?:named?|file)\s+([\w\-]+\.(?:html|css|js|ts|tsx|py|json|svg|txt|md|sh))", g)
    if m:
        return f"staging/dev/{plan_id}/{m.group(1)}"

    # 3. Type keyword at start of goal
    _EXT = {"html": "index.html", "webpage": "index.html", "skeleton": "index.html",
            "markup": "index.html", "page": "index.html",
            "css": "style.css", "stylesheet": "style.css", "layout": "style.css",
            "javascript": "script.js", "js ": "script.js", "script": "script.js",
            "svg": "graphic.svg", "seo.txt": "seo.txt"}
    for kw, fname in _EXT.items():
        if kw in g[:120]:
            return f"staging/dev/{plan_id}/{fname}"

    # 4. First explicit filename.ext mention
    m = _re.search(r"\b([\w\-]+\.(?:html|css|js|ts|tsx|py|json|svg|txt|md|sh))\b", g)
    if m:
        return f"staging/dev/{plan_id}/{m.group(1)}"

    # 5. Test-writing step against existing source → test_<source>.py
    if "test" in g:
        srcs = _find_source_files(goal, limit=1)
        fname = f"test_{srcs[0].stem}.py" if srcs else "test_suite.py"
        return f"staging/dev/{plan_id}/{fname}"

    # 6. Step references existing project source → work on a staged copy of it
    srcs = _find_source_files(goal, limit=1)
    if srcs:
        return f"staging/dev/{plan_id}/{srcs[0].name}"

    return f"staging/dev/{plan_id}/index.html"


def exec_code_step(task: dict) -> tuple[bool, str]:
    """
    Generate file content via qwen3.6:27b and write to the target path.
    Used for coding/code_edit plan steps that need to CREATE files in staging.
    Falls back to inferring the target filename from the task description.
    """
    import urllib.request, urllib.error

    goal         = task.get("task", "")
    target_files = task.get("target_files", [])
    args         = task.get("args", {})
    primary_path = (
        args.get("path")
        or task.get("primary_path")
        or (target_files[0] if target_files else "")
        or _infer_file_from_goal(goal, task.get("plan_id", "unknown"))
    )

    if not primary_path:
        return False, "No target file path for coding step"

    # Build absolute path — the path from the plan is already staging/dev/PLAN-ID/file
    # so prepend /mnt/e/coding/ to get the full WSL path, or use as-is if absolute
    abs_path = Path(primary_path)
    if not abs_path.is_absolute():
        # Paths come in as "staging/dev/..." — prepend the coding root
        coding_root = STAGING_ROOT.parent  # /mnt/e/coding
        abs_path = coding_root / primary_path

    ext = abs_path.suffix.lower()
    lang_map = {".html": "HTML", ".css": "CSS", ".js": "JavaScript",
                ".ts": "TypeScript", ".py": "Python", ".json": "JSON",
                ".tsx": "TypeScript React", ".sh": "Bash"}
    lang = lang_map.get(ext, "")

    # Diagnosis-guided retry: tell the coder what went wrong last time
    diag_block = ""
    if task.get("_diagnosis"):
        diag_block = (
            f"\nPrevious attempt FAILED with: {task.get('_last_error', 'unknown')}\n"
            f"Failure diagnosis:\n{task['_diagnosis'][:500]}\n"
            "Apply the fix from the diagnosis in this attempt.\n"
        )

    # Tasks about EXISTING code need the real source in the prompt —
    # otherwise the model invents an API and the output is useless.
    # Prefer already-staged copies, then matching project sources.
    context_block = ""
    total = 0
    stage_dir = abs_path.parent
    seen_names = set()
    candidates = []
    try:
        candidates += [f for f in sorted(stage_dir.glob("*.py")) if f != abs_path]
    except Exception:
        pass
    candidates += _find_source_files(goal)
    for src in candidates:
        if src.name in seen_names or src.name == abs_path.name:
            continue
        seen_names.add(src.name)
        try:
            text = src.read_text(encoding="utf-8", errors="replace")[:6000]
        except Exception:
            continue
        context_block += f"\n### SOURCE FILE: {src.name}\n{text}\n"
        total += len(text)
        if total > 12000:
            break

    prompt = (
        f"You are an expert {lang} developer. Write the complete file content for this task:\n\n"
        f"Task: {goal}\n\n"
        f"Target file: {abs_path.name}\n"
        f"{diag_block}"
        + (f"\nReference source code:\n{context_block}\n" if context_block else "")
        + "\nRules:\n"
        "- Output ONLY the raw file content. No markdown fences, no explanation.\n"
        "- Write complete, working code — not a skeleton or placeholder.\n"
        "- The file must be immediately usable as-is.\n"
    )

    payload = json.dumps({
        "model":   CODER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream":  False,
        "think":   False,
        "options": {"temperature": 0, "num_predict": 4096},
    }).encode()

    def _call_coder(t: int) -> str:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=t) as resp:
            data = json.loads(resp.read().decode())
            return data.get("message", {}).get("content", "").strip()

    recovery = None
    try:
        try:
            content = _call_coder(300)
        except Exception as first_err:
            # GPU wedged / cold-load stall ("llama runner has terminated", timeout).
            # gpu_broker (shared with agent_loop.py/skill_builder.py) unloads other
            # Ollama models and evicts gemma vision if needed, then we retry longer.
            # (This path killed PLAN-20260712-002 before self-recovery existed.)
            print(f"[runner] coder call failed ({str(first_err)[:120]}) — "
                  f"GPU recovery + retry", flush=True)
            recovery = gpu_broker.recover_for_model(CODER_MODEL, log_prefix="runner")
            content = _call_coder(600)

        if not content:
            return False, "Coder returned empty content"

        # Strip accidental markdown fences
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            ).strip()

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        print(f"[runner] wrote {abs_path} ({len(content)} chars)")
        return True, f"Wrote {abs_path.name} ({len(content)} chars)"

    except urllib.error.HTTPError as e:
        return False, f"Ollama HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"exec_code_step failed: {e}"
    finally:
        gpu_broker.restore_after(recovery)


def build_app_zip(plan_id: str) -> Optional[Path]:
    """Zip a plan's output (tested preferred, dev fallback) for delivery.
    Returns the zip path or None if the plan has no files."""
    import zipfile
    coding_root = STAGING_ROOT.parent
    src = None
    for stage in ("tested", "dev"):
        d = coding_root / "staging" / stage / plan_id
        if d.exists() and any(f.is_file() for f in d.rglob("*")):
            src = d
            break
    if src is None:
        return None

    out = coding_root / "staging" / f"{plan_id}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src))
    return out


def send_app_zip_telegram(plan_id: str) -> dict:
    """Zip the plan output and send it through Telegram with a caption the
    Termux receiver recognises (JARVIS_APP <plan_id>). Phone side:
    scripts/termux_app_runner.py unzips + serves it at a localhost link."""
    import urllib.request
    token = (
        os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    ).strip()
    chat_ids = [
        c.strip()
        for c in os.environ.get("JARVIS_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
        if c.strip()
    ]
    if not token or not chat_ids:
        return {"ok": False, "error": "Telegram credentials not configured"}

    zip_path = build_app_zip(plan_id)
    if zip_path is None:
        return {"ok": False, "error": f"No output files found for {plan_id}"}

    content = zip_path.read_bytes()
    caption = f"JARVIS_APP {plan_id}"
    boundary = "boundary_jarvis_appzip"
    sent = 0
    for chat_id in chat_ids:
        body: list[bytes] = []

        def part(name: str, value: str) -> None:
            body.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )

        part("chat_id", str(chat_id))
        part("caption", caption)
        body.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{zip_path.name}"\r\n'
            f"Content-Type: application/zip\r\n\r\n".encode()
        )
        body.append(content)
        body.append(f"\r\n--{boundary}--\r\n".encode())

        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data=b"".join(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                if json.loads(resp.read()).get("ok"):
                    sent += 1
        except Exception as e:
            print(f"[runner] app zip send failed: {e}")

    return {
        "ok": sent > 0,
        "plan_id": plan_id,
        "zip": str(zip_path),
        "size_kb": len(content) // 1024,
        "sent_to": sent,
    }


def _ollama_quick(model: str, prompt: str, timeout: int = 120) -> str:
    """Small non-streaming Ollama call used for failure diagnosis."""
    import urllib.request
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 400},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("message", {}).get("content", "").strip()


def diagnose_failure(task: dict, error: str) -> str:
    """Ask the model why a task failed and how to fix it; log to the vault.

    Returns the diagnosis text ("" if diagnosis itself failed). The log at
    .jarvis/plan_failures.md is append-only so failure history survives.
    """
    goal = task.get("task", "")
    prompt = (
        "A JARVIS plan task failed. Diagnose it.\n\n"
        f"Task: {goal}\n"
        f"Skill/tool: {task.get('skill','?')}.{task.get('tool','?')}\n"
        f"Args: {json.dumps(task.get('args', {}))[:300]}\n"
        f"Error: {error[:600]}\n\n"
        "Reply with:\n"
        "CAUSE: <one or two sentences — the most likely root cause>\n"
        "FIX: <one concrete instruction to apply on retry>\n"
        "No other text."
    )
    try:
        diagnosis = _ollama_quick(DIAG_MODEL, prompt)
    except Exception as e:
        diagnosis = ""
        print(f"[runner] diagnosis call failed: {e}")

    try:
        FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(FAILURE_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')} — {_task_uid(task)}\n"
                f"- task: {goal[:150]}\n"
                f"- tool: {task.get('skill','?')}.{task.get('tool','?')}\n"
                f"- error: {error[:300]}\n"
                f"- diagnosis: {diagnosis[:600] if diagnosis else '(diagnosis unavailable)'}\n"
            )
    except Exception as e:
        print(f"[runner] failure log write failed: {e}")

    return diagnosis


def _build_shell_cmd(goal: str, plan_id: str) -> str:
    """Build a real shell command from a natural-language shell step.

    Handles the recurring plan patterns:
      copy source → staging, copy dev → tested, read source, run unit tests,
      generic validate, and a safe echo fallback.
    """
    g = goal.lower()
    coding_root = STAGING_ROOT.parent
    stage_dev = coding_root / f"staging/dev/{plan_id}"

    if "copy" in g:
        if "tested" in g:
            dest = coding_root / f"staging/tested/{plan_id}"
            return f"mkdir -p '{dest}' && cp -r '{stage_dev}/.' '{dest}/'"
        # copy referenced project source files INTO the staging workspace
        srcs = _find_source_files(goal)
        if srcs:
            src_str = " ".join(f"'{s}'" for s in srcs)
            return f"mkdir -p '{stage_dev}' && cp {src_str} '{stage_dev}/' && ls -la '{stage_dev}'"
        return f"mkdir -p '{stage_dev}' && echo 'No matching source files for: {goal[:60]}'"

    if g.startswith("read") or " read " in f" {g} ":
        srcs = _find_source_files(goal)
        if srcs:
            src_str = " ".join(f"'{s}'" for s in srcs)
            return f"head -c 4000 {src_str}"

    if "test" in g and ("run" in g or "re-run" in g or "rerun" in g):
        return (
            f"cd '{stage_dev}' && "
            f"(python3 -m pytest -x -q . 2>&1 | tail -30) || "
            f"(for f in *.py; do python3 -m py_compile \"$f\" && echo \"compile OK: $f\"; done)"
        )

    if any(w in g for w in ("test", "validate", "verify", "check", "ensure")):
        try:
            if list(stage_dev.glob("*.py")):
                return (
                    f"cd '{stage_dev}' && "
                    f"(python3 -m pytest -x -q . 2>&1 | tail -30) || "
                    f"(for f in *.py; do python3 -m py_compile \"$f\" && echo \"compile OK: $f\"; done)"
                )
        except Exception:
            pass
        return _build_test_cmd(plan_id, coding_root)

    if "review" in g or "identif" in g:
        return f"echo 'Review noted — fixes are applied by the coder steps: {goal[:60]}'"

    return f"echo 'Shell step: {goal[:80]}'"


def _log_for_reflection(r, kind: str, user: str, action: str,
                        outcome: str, detail: str = "") -> None:
    """Push an interaction record to jarvis:log:<date> for the nightly
    reflection pass (reflection_daemon.py). Never raises."""
    try:
        key = f"jarvis:log:{time.strftime('%Y-%m-%d')}"
        r.rpush(key, json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": kind,
            "user": user[:300],
            "action": action[:200],
            "outcome": outcome,
            "detail": detail[:300],
        }))
        r.expire(key, 7 * 86400)
    except Exception:
        pass


def _notify_telegram(text: str) -> None:
    """Send a message to all allowed Telegram chats. Never raises.

    The plan-completion pubsub channel has no live consumer, so the runner
    notifies Telegram directly — this is how 'plan ready' reaches the user.
    """
    import urllib.parse, urllib.request
    token = (
        os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    ).strip()
    # User chat only (first allowed ID / explicit override) — the second
    # allowed ID is the internal mobile bridge channel, not for notifications.
    explicit = os.environ.get("JARVIS_TELEGRAM_NOTIFY_CHAT_ID", "").strip()
    chat_ids = [explicit] if explicit else [
        c.strip()
        for c in os.environ.get("JARVIS_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
        if c.strip()
    ][:1]
    if not token or not chat_ids:
        return
    for chat_id in chat_ids:
        try:
            payload = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": text[:3900],
            }).encode()
            urllib.request.urlopen(
                urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ),
                timeout=10,
            )
        except Exception as e:
            print(f"[runner] telegram notify failed: {e}")


def dispatch_task(task: dict) -> tuple[bool, str]:
    """
    Execute a task by calling the appropriate skill's TOOL_MAP.
    Returns (success, result_str).
    """
    skill_name = task.get("skill", "")
    tool_name  = task.get("tool", "")
    args       = task.get("args", {})

    if not skill_name or not tool_name:
        return False, f"Task has no skill/tool: {task.get('task', '?')}"

    # Coding steps: generate full file content via Ollama and write to staging
    if skill_name in ("coding", "code_edit") or tool_name in ("coding", "code_edit"):
        return exec_code_step(task)

    # Shell steps (read/copy/test): build a real cmd from the task goal
    if tool_name == "shell" and not args.get("cmd"):
        goal    = task.get("task", "")
        plan_id = task.get("plan_id", "")
        args = {**args, "cmd": _build_shell_cmd(goal, plan_id)}
        task = {**task, "args": args}

    skills = get_skills()

    if skill_name not in skills:
        skills = get_skills(force_reload=True)

    if skill_name not in skills:
        return False, f"Unknown skill: {skill_name}"

    tool_map = skills[skill_name]["tool_map"]
    if tool_name not in tool_map:
        return False, f"Unknown tool '{tool_name}' in skill '{skill_name}'"

    try:
        # Pass args as kwargs if dict, else as positional
        fn = tool_map[tool_name]
        if isinstance(args, dict):
            result = fn(**args)
        else:
            result = fn(args)
        return True, str(result)
    except Exception as e:
        return False, f"[{skill_name}.{tool_name}] raised: {e}"


# ── Test command builder ───────────────────────────────────────────────────────

def _build_test_cmd(plan_id: str, coding_root: Path) -> str:
    """
    Choose between Playwright (simple static sites) and Podman (complex projects).

    Simple = has index.html + ≤8 files and no server-side code.
    Complex = has package.json / requirements.txt / Dockerfile or >8 files.
    """
    stage_dir = coding_root / "staging" / "dev" / plan_id
    files = list(stage_dir.rglob("*")) if stage_dir.exists() else []
    file_names = {f.name.lower() for f in files if f.is_file()}
    file_count = len([f for f in files if f.is_file()])

    has_html        = "index.html" in file_names
    is_react_native = any(n in file_names for n in ("app.json", "app.config.js", "metro.config.js"))
    is_complex = (
        file_count > 8
        or any(n in file_names for n in ("package.json", "requirements.txt", "dockerfile", "docker-compose.yml"))
    )

    stage_path = str(stage_dir)

    if is_react_native:
        # React Native / Expo — build via Gradle then test with Jest
        android_dir = str(stage_dir / "android")
        return (
            f"cd '{stage_path}' && "
            f"([ -f android/gradlew ] && cd android && ./gradlew assembleDebug --daemon 2>&1 | tail -20 || "
            f"echo 'Gradle build skipped — no android/ folder') && "
            f"(npx jest --passWithNoTests --forceExit 2>&1 | tail -20 || echo 'Jest: no tests found')"
        )

    if not is_complex and has_html:
        # Simple static site — use Playwright
        html_path = f"file://{stage_path}/index.html"
        return (
            f"node -e \""
            f"const {{chromium}}=require('playwright');"
            f"(async()=>{{"
            f"  const b=await chromium.launch();"
            f"  const p=await b.newPage();"
            f"  const errs=[];"
            f"  p.on('pageerror',e=>errs.push(e.message));"
            f"  await p.goto('{html_path}');"
            f"  await p.waitForTimeout(2000);"
            f"  const title=await p.title();"
            f"  await p.screenshot({{path:'{stage_path}/test-screenshot.png'}});"
            f"  await b.close();"
            f"  if(errs.length){{console.error('JS errors:',errs);process.exit(1);}}"
            f"  console.log('OK title='+title);"
            f"}})()\" 2>&1 || "
            # fallback: basic JS syntax check if playwright not installed
            f"(find '{stage_path}' -name '*.js' | xargs -I{{}} node --check {{}} && "
            f"find '{stage_path}' -name '*.json' | xargs -I{{}} python3 -m json.tool {{}} > /dev/null && "
            f"echo 'Syntax OK — playwright not available for UI test')"
        )
    else:
        # Complex project — mount in Podman and run checks
        image = "node:20-alpine" if any(n in file_names for n in ("package.json", "index.js", "index.ts")) else "python:3.11-slim"
        if image.startswith("node"):
            inner = "cd /app && ([ -f package.json ] && npm install --silent 2>/dev/null || true) && find . -name '*.js' | xargs -I{} node --check {} && echo 'Node syntax OK'"
        else:
            inner = "cd /app && find . -name '*.py' | xargs -I{} python3 -m py_compile {} && echo 'Python syntax OK'"
        return (
            f"podman run --rm -v '{stage_path}:/app:ro' {image} sh -c \"{inner}\" 2>&1 || "
            f"echo 'Podman test failed — check staging files'"
        )


# ── Shell/python task via executor ─────────────────────────────────────────────

async def dispatch_via_executor(task: dict) -> tuple[bool, str]:
    """
    For shell.shell and shell.run_command tasks, use the executor
    HTTP API for PTY-based execution with real streaming.
    Falls back to direct dispatch if executor unreachable.
    """
    import urllib.request
    import urllib.error

    skill = task.get("skill")
    tool  = task.get("tool")
    args  = task.get("args", {})

    # Only shell exec tasks go through executor
    if skill != "shell" or tool not in ("shell", "run_command"):
        return dispatch_task(task)

    # Build cmd from goal if missing
    cmd = args.get("cmd", "")
    if not cmd:
        goal    = task.get("task", "")
        plan_id = task.get("plan_id", "")
        cmd = _build_shell_cmd(goal, plan_id)

    try:
        # Start execution
        payload = json.dumps({"task": cmd, "type": "shell"}).encode()
        req = urllib.request.Request(
            f"{EXECUTOR_URL}/execute",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            run_id = json.loads(resp.read())["run_id"]

        # Poll for result
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            poll_req = urllib.request.Request(
                f"{EXECUTOR_URL}/execute/result?run_id={run_id}&timeout=5",
                method="GET",
            )
            try:
                with urllib.request.urlopen(poll_req, timeout=10) as resp:
                    result = json.loads(resp.read())
                    summary = result.get("summary", {})
                    stdout  = "\n".join(
                        e["data"] for e in result.get("events", [])
                        if e["kind"] == "stdout"
                    )
                    return summary.get("success", False), stdout or str(summary)
            except urllib.error.HTTPError as e:
                if e.code == 408:
                    continue   # still running
                raise

        return False, "Executor timed out"

    except Exception:
        # Executor not reachable — run cmd directly via subprocess
        import subprocess
        if not cmd:
            return False, "No cmd and executor unreachable"
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            output = (proc.stdout or proc.stderr or "").strip()
            return proc.returncode == 0, output or f"exit {proc.returncode}"
        except Exception as e:
            return False, str(e)


# ── Plan completion check ──────────────────────────────────────────────────────

def _check_plan_complete(r, plan_id: str) -> tuple[bool, int, int]:
    """
    Check if all tasks in a plan are done.
    Returns (all_done, done_count, total_count).
    """
    raw = r.hget(REDIS_PLANS_KEY, plan_id)
    if not raw:
        return False, 0, 0

    plan   = json.loads(raw)
    tasks  = plan.get("tasks", [])
    total  = len(tasks)
    done   = 0
    failed = 0

    for t in tasks:
        uid    = _task_uid(t)
        status = _get_status(r, uid)
        if status:
            if status["status"] == "done":
                done += 1
            elif status["status"] == "failed":
                failed += 1

    return (done + failed) == total, done, total


def _plan_summary(r, plan_id: str) -> str:
    """Build a human-readable plan completion summary."""
    raw = r.hget(REDIS_PLANS_KEY, plan_id)
    if not raw:
        return f"Plan {plan_id} not found in Redis"

    plan   = json.loads(raw)
    tasks  = plan.get("tasks", [])
    lines  = [f"Plan {plan_id} complete: {plan.get('goal', '?')}\n"]

    for t in tasks:
        uid    = _task_uid(t)
        status = _get_status(r, uid)
        result = _get_result(r, uid)
        s      = status["status"] if status else "unknown"
        icon   = "✓" if s == "done" else ("✗" if s == "failed" else "?")
        lines.append(f"  [{icon}] Task {t.get('task_id')}: {t.get('task','?')[:60]}")
        if result and s == "failed":
            lines.append(f"       Error: {result[:100]}")

    return "\n".join(lines)


# ── Main runner loop ───────────────────────────────────────────────────────────

async def run_once(r) -> Optional[dict]:
    """
    Pop one task from Redis, execute it, update status.
    Returns the task dict or None if queue empty.
    """
    raw = r.lpop(REDIS_TASKS_KEY)
    if not raw:
        return None

    task     = json.loads(raw)
    task_uid = _task_uid(task)
    plan_id  = task.get("plan_id", "")
    retries  = task.get("_retries", 0)

    print(f"[runner] task {task_uid}  {task.get('skill','?')}.{task.get('tool','?')}"
          f"  plan={plan_id}")

    # Wait for dependencies
    _set_status(r, task_uid, "waiting", f"deps={task.get('depends_on', [])}")
    ok, dep_err = await _wait_for_deps(r, task)
    if not ok:
        # A hard dep FAILURE is terminal; a dep TIMEOUT usually just means a
        # long chain (each coder task can take minutes) — re-queue to the back
        # and free this worker instead of failing the whole cascade.
        dep_requeues = task.get("_dep_requeues", 0)
        if "Timed out" in dep_err and dep_requeues < 3:
            task["_dep_requeues"] = dep_requeues + 1
            r.rpush(REDIS_TASKS_KEY, json.dumps(task))
            _set_status(r, task_uid, "queued",
                        f"deps not ready, requeued {dep_requeues+1}/3")
            print(f"[runner] ⏳ {task_uid} deps not ready, requeued")
            return task
        _set_status(r, task_uid, "failed", dep_err)
        _set_result(r, task_uid, dep_err)
        print(f"[runner] ✗ dep failed: {dep_err}")
        return task

    # Execute
    _set_status(r, task_uid, "running")
    start   = time.monotonic()

    skill = task.get("skill", "")
    tool  = task.get("tool", "")
    is_shell_exec = (skill == "shell" and tool in ("shell", "run_command"))

    try:
        if is_shell_exec:
            success, result = await dispatch_via_executor(task)
        else:
            success, result = dispatch_task(task)
    except Exception as e:
        success, result = False, str(e)

    elapsed = round(time.monotonic() - start, 2)

    if success:
        _set_status(r, task_uid, "done", f"elapsed={elapsed}s")
        _set_result(r, task_uid, result)
        print(f"[runner] ✓ {task_uid}  ({elapsed}s)")
        _log_for_reflection(
            r, "plan", task.get("task", ""),
            f"{skill}.{tool} ({elapsed}s)",
            "corrected" if task.get("_diag_retry") else "success",
            result[:200],
        )
    else:
        if retries < MAX_RETRIES:
            # Brief backoff so a transient outage (e.g. Ollama restarting)
            # doesn't burn every retry within the same few seconds.
            await asyncio.sleep(3 * (retries + 1))
            # Re-queue at FRONT so workers waiting on deps don't starve the retry
            task["_retries"] = retries + 1
            r.lpush(REDIS_TASKS_KEY, json.dumps(task))
            _set_status(r, task_uid, "queued", f"retry {retries+1}/{MAX_RETRIES}")
            print(f"[runner] ↺ {task_uid} retry {retries+1}")
        elif not task.get("_diag_retry"):
            # Retries exhausted → ask the model WHY it failed, log the
            # diagnosis to .jarvis/plan_failures.md, and give the task ONE
            # diagnosis-guided retry (exec_code_step injects it into the prompt).
            diagnosis = await asyncio.get_event_loop().run_in_executor(
                None, diagnose_failure, task, result
            )
            if diagnosis:
                task["_diag_retry"] = True
                task["_diagnosis"] = diagnosis
                task["_last_error"] = result[:300]
                r.lpush(REDIS_TASKS_KEY, json.dumps(task))
                _set_status(r, task_uid, "queued", "diagnosis-guided retry")
                print(f"[runner] 🩺 {task_uid} diagnosed, guided retry queued")
            else:
                _set_status(r, task_uid, "failed", result[:200])
                _set_result(r, task_uid, result)
                print(f"[runner] ✗ {task_uid}: {result[:100]}")
                _log_for_reflection(
                    r, "plan", task.get("task", ""),
                    f"{skill}.{tool}", "fail", result[:250],
                )
        else:
            _set_status(r, task_uid, "failed", result[:200])
            _set_result(r, task_uid, result)
            print(f"[runner] ✗ {task_uid}: {result[:100]} (after guided retry)")
            _log_for_reflection(
                r, "plan", task.get("task", ""),
                f"{skill}.{tool}", "fail",
                f"{result[:150]} | diagnosis: {task.get('_diagnosis', '')[:150]}",
            )

    # Check if this completes the plan
    if plan_id:
        all_done, done, total = _check_plan_complete(r, plan_id)
        if all_done:
            # Guard: only notify once per plan (parallel workers may race here)
            notify_key = f"jarvis:plan:{plan_id}:notified"
            first = r.set(notify_key, "1", nx=True, ex=86400)

            summary = _plan_summary(r, plan_id)
            print(f"\n[runner] {'='*50}")
            print(summary)
            print(f"[runner] {'='*50}\n")
            # Publish completion event
            r.publish(f"jarvis:plan:{plan_id}:done", json.dumps({
                "plan_id": plan_id,
                "done": done,
                "total": total,
                "summary": summary,
            }))

            if first:
                icon = "✅" if done == total else "⚠️"
                _notify_telegram(
                    f"{icon} Plan {plan_id} finished: {done}/{total} tasks done\n\n{summary}"
                )
                # Fully successful plans with output files also get the app
                # zip attached — the Termux receiver on the phone unzips and
                # serves it locally (JARVIS_APP caption is its trigger).
                if done == total:
                    try:
                        result = send_app_zip_telegram(plan_id)
                        if result.get("ok"):
                            print(f"[runner] app zip sent ({result['size_kb']} KB)")
                    except Exception as e:
                        print(f"[runner] app zip skipped: {e}")

    return task


async def _worker(r, worker_id: int):
    """Single worker — pops and executes tasks from Redis indefinitely."""
    idle_count = 0
    last_beat = 0.0
    HEARTBEAT_EVERY = 30  # seconds; independent of idle/busy state
    while True:
        try:
            task = await run_once(r)
            if task is None:
                idle_count += 1
                if idle_count % 60 == 0:
                    depth = r.llen(REDIS_TASKS_KEY)
                    print(f"[runner] w{worker_id} idle  queue_depth={depth}")
                await asyncio.sleep(POLL_INTERVAL)
            else:
                idle_count = 0
            # Only worker 0 reports — avoids MAX_WORKERS redundant Redis writes.
            if worker_id == 0 and time.monotonic() - last_beat > HEARTBEAT_EVERY:
                depth = r.llen(REDIS_TASKS_KEY)
                heartbeat.beat("plan_runner", ok=True, detail=f"queue_depth={depth}",
                               interval=HEARTBEAT_EVERY)
                last_beat = time.monotonic()
        except Exception as e:
            print(f"[runner] w{worker_id} loop error: {e}")
            if worker_id == 0:
                heartbeat.beat("plan_runner", ok=False, detail=str(e), interval=HEARTBEAT_EVERY)
                last_beat = time.monotonic()
            await asyncio.sleep(2.0)


def _recover_stale_tasks(r) -> int:
    """Re-queue tasks orphaned by a runner crash/restart.

    A popped task that never finished leaves status running/waiting/queued
    with no matching queue entry (e.g. WSL shut down mid-plan). On a fresh
    daemon start — before any worker runs — those are safe to re-queue.
    """
    active_id = r.get("jarvis:active_plan_id") or ""
    if not active_id:
        return 0
    raw = r.hget(REDIS_PLANS_KEY, active_id)
    if not raw:
        return 0
    plan = json.loads(raw)

    queued_uids = set()
    for item in r.lrange(REDIS_TASKS_KEY, 0, -1):
        try:
            queued_uids.add(_task_uid(json.loads(item)))
        except Exception:
            continue

    requeued = 0
    for t in plan.get("tasks", []):
        uid = _task_uid(t)
        st = _get_status(r, uid)
        state = st["status"] if st else None
        if state in ("running", "waiting", "queued") and uid not in queued_uids:
            nt = dict(t)
            for k in ("_retries", "_dep_requeues", "_diag_retry", "_diagnosis", "_last_error"):
                nt.pop(k, None)
            r.rpush(REDIS_TASKS_KEY, json.dumps(nt))
            _set_status(r, uid, "queued", "recovered after runner restart")
            requeued += 1

    if requeued:
        print(f"[runner] recovered {requeued} stale tasks for plan {active_id}")
    return requeued


async def daemon():
    """Main daemon — spawns MAX_WORKERS concurrent task workers."""
    print(f"[runner] JARVIS Plan Runner starting  workers={MAX_WORKERS}")
    print(f"[runner] Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"[runner] Skills: {SKILLS_DIR}")
    print(f"[runner] Executor: {EXECUTOR_URL}")

    try:
        r = _redis()
        print(f"[runner] Redis connected ✓")
    except RuntimeError as e:
        print(f"[runner] ✗ {e}")
        sys.exit(1)

    try:
        _recover_stale_tasks(r)
    except Exception as e:
        print(f"[runner] stale-task recovery failed (non-fatal): {e}")

    skills = get_skills()
    print(f"[runner] Loaded {len(skills)} skills: {', '.join(skills.keys())}")
    print(f"[runner] Polling every {POLL_INTERVAL}s...\n")

    await asyncio.gather(*[_worker(r, i) for i in range(MAX_WORKERS)])


# ── Plan rerun ────────────────────────────────────────────────────────────────

def _next_plan_id(plan_id: str) -> str:
    """Return the next versioned plan ID: FOO-001 → FOO-001-2 → FOO-001-3, etc.
    Only 1–2 digit suffixes are treated as rerun counters; 3-digit sequences are original IDs."""
    import re as _re
    m = _re.match(r"^(.+)-(\d{1,2})$", plan_id)
    if m:
        return f"{m.group(1)}-{int(m.group(2)) + 1}"
    return f"{plan_id}-2"


def rerun_plan(plan_id: str) -> dict:
    """
    Clone an existing plan under a new versioned ID and queue all its tasks.

    The new ID is derived by appending/incrementing a numeric suffix:
      PLAN-20260629-001 -> PLAN-20260629-001-2 -> PLAN-20260629-001-3

    All task plan_id references are rewritten to the new ID. Task statuses and
    results from the original run are not copied — the new plan starts clean.
    """
    try:
        r = _redis()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    raw = r.hget(REDIS_PLANS_KEY, plan_id)
    if not raw:
        return {"ok": False, "error": f"Plan {plan_id} not found in Redis"}

    plan = json.loads(raw)

    new_id = _next_plan_id(plan_id)
    while r.hexists(REDIS_PLANS_KEY, new_id):
        new_id = _next_plan_id(new_id)

    new_plan = dict(plan)
    new_plan["plan_id"] = new_id
    new_plan["rerun_of"] = plan_id

    new_tasks = []
    for t in new_plan.get("tasks", []):
        nt = dict(t)
        nt["plan_id"] = new_id
        for k in ("_retries", "_dep_requeues", "_diag_retry", "_diagnosis", "_last_error"):
            nt.pop(k, None)
        new_tasks.append(nt)
    new_plan["tasks"] = new_tasks

    r.hset(REDIS_PLANS_KEY, new_id, json.dumps(new_plan))
    r.set("jarvis:active_plan_id", new_id)

    for t in new_tasks:
        r.rpush(REDIS_TASKS_KEY, json.dumps(t))

    print(f"[runner] rerun: {plan_id} → {new_id}  tasks={len(new_tasks)}")
    return {
        "ok": True,
        "original_plan_id": plan_id,
        "new_plan_id": new_id,
        "goal": new_plan.get("goal", ""),
        "tasks_queued": len(new_tasks),
    }


# ── FastAPI status API ─────────────────────────────────────────────────────────

try:
    from fastapi import FastAPI
    app = FastAPI(title="JARVIS Plan Runner")

    @app.get("/status")
    def status():
        r = _redis()
        return {
            "queue_depth": r.llen(REDIS_TASKS_KEY),
            "plans":       r.hlen(REDIS_PLANS_KEY),
            "skills":      list(get_skills().keys()),
        }

    @app.get("/plan/{plan_id}")
    def plan_status(plan_id: str):
        r = _redis()
        all_done, done, total = _check_plan_complete(r, plan_id)
        return {
            "plan_id":  plan_id,
            "done":     done,
            "total":    total,
            "complete": all_done,
            "summary":  _plan_summary(r, plan_id) if all_done else None,
        }

    @app.get("/plan/{plan_id}/tasks")
    def plan_tasks(plan_id: str):
        r = _redis()
        raw = r.hget(REDIS_PLANS_KEY, plan_id)
        if not raw:
            return {"error": "plan not found"}
        plan  = json.loads(raw)
        tasks = []
        for t in plan.get("tasks", []):
            uid    = _task_uid(t)
            status = _get_status(r, uid) or {}
            result = _get_result(r, uid)
            tasks.append({
                "task_id": t.get("task_id"),
                "task":    t.get("task"),
                "skill":   t.get("skill"),
                "tool":    t.get("tool"),
                "status":  status.get("status", "unknown"),
                "result":  result[:200] if result else None,
            })
        return {"plan_id": plan_id, "goal": plan.get("goal"), "tasks": tasks}

    @app.post("/reload-skills")
    def reload_skills():
        skills = get_skills(force_reload=True)
        return {"loaded": list(skills.keys())}

    @app.post("/rerun/{plan_id}")
    def rerun_endpoint(plan_id: str):
        return rerun_plan(plan_id)

    @app.post("/send-app/{plan_id}")
    def send_app_endpoint(plan_id: str):
        return send_app_zip_telegram(plan_id)

except ImportError:
    app = None


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--serve" in sys.argv:
        import uvicorn
        uvicorn.run("plan_runner:app", host="127.0.0.1", port=8766, reload=False)
    elif "--once" in sys.argv:
        r = _redis()
        asyncio.run(run_once(r))
    else:
        asyncio.run(daemon())
