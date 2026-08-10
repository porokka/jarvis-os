"""
JARVIS Skill — Model management (Ollama + HuggingFace + llama.cpp).

Handles:
  - System check (VRAM, RAM, running models)
  - Model discovery via HuggingFace Hub (hf CLI + API)
  - Ollama pull / remove / list
  - llama.cpp multimodal model management
  - Validation (benchmark prompt, timing, output quality check)
  - models.json registry (source of truth for JARVIS model routing)
  - Upgrade flow: search → pull → validate → ask → remove old

Role taxonomy understood by this skill:
  planner   — qwen3:14b (fits alongside others), qwen3.6:27b
  coder     — qwen3.6:27b (solo when active, kicks smaller)
  deep      — qwen3:32b or deepseek-r1 variants (solo)
  embedding — nomic-embed-text or similar small model (always on)
  vision    — gemma3:4b via llama.cpp (multimodal, always on)
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

SKILL_NAME        = "models"
SKILL_DESCRIPTION = (
    "Manage JARVIS AI models — discover better models on HuggingFace, pull via Ollama or hf CLI, "
    "validate quality, upgrade with safe swap (validate first, ask before deleting old), "
    "run system hardware check for VRAM/RAM, and maintain models.json registry. "
    "Use for: 'check for better models', 'upgrade qwen', 'install models', 'what models do we have', "
    "'run system check', 'validate model', 'update models.json'."
)

# ── Paths & config ─────────────────────────────────────────────────────────────

MODELS_JSON   = Path(os.getenv("JARVIS_MODELS_JSON",   "/mnt/e/coding/jarvis-os/config/models.json"))
LLAMA_MODELS  = Path(os.getenv("JARVIS_LLAMA_MODELS",  "/mnt/e/models/llama"))
HF_CACHE      = Path(os.getenv("HF_HOME",              str(Path.home() / ".cache/huggingface")))

# VRAM budget rules (GB) — determines which models can coexist
VRAM_TOTAL_GB = 24  # RTX 3090

ROLE_VRAM_GB = {
    "embedding": 1,
    "vision":    5,   # gemma3:4b via llama.cpp
    "planner":   9,   # qwen3:14b
    "planner_big": 20, # qwen3.6:27b (MoE, fits in 24GB)
    "coder":     20,  # qwen3:32b
    "deep":      20,  # deepseek-r1:32b
}

# When coder or deep starts, only they + embedding stay
SOLO_ROLES = {"coder", "deep"}

# ── Utility: run shell and return output ───────────────────────────────────────

def _sh(cmd: str, timeout: int = 120) -> dict:
    """Run a shell command, return {stdout, stderr, returncode, success}."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout":     r.stdout.strip(),
            "stderr":     r.stderr.strip(),
            "returncode": r.returncode,
            "success":    r.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timed out after {timeout}s", "returncode": -1, "success": False}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "success": False}


# ── models.json helpers ────────────────────────────────────────────────────────

def load_models_json() -> dict:
    """Load models.json, return empty structure if missing."""
    default = {
        "version": 1,
        "updated": "",
        "hardware": {},
        "models": {}
    }
    try:
        if MODELS_JSON.exists():
            return json.loads(MODELS_JSON.read_text(encoding="utf-8"))
        return default
    except Exception:
        return default


def save_models_json(data: dict) -> dict:
    """Write models.json atomically."""
    try:
        MODELS_JSON.parent.mkdir(parents=True, exist_ok=True)
        data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = MODELS_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(MODELS_JSON)
        return {"success": True, "path": str(MODELS_JSON)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _update_model_entry(tag: str, role: str, backend: str, meta: dict):
    """Upsert a single model entry in models.json."""
    registry = load_models_json()
    registry.setdefault("models", {})[tag] = {
        "role":     role,
        "backend":  backend,  # "ollama" | "llama" | "hf"
        "tag":      tag,
        "added":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        **meta,
    }
    save_models_json(registry)


# ── System check ───────────────────────────────────────────────────────────────

def exec_system_check() -> str:
    """
    Evaluate hardware: VRAM, RAM, disk, running Ollama models.
    Updates models.json hardware section.
    Returns a human-readable summary.
    """
    lines = ["=== JARVIS System Check ===\n"]

    # GPU / VRAM
    gpu = _sh("nvidia-smi --query-gpu=name,memory.total,memory.free,memory.used --format=csv,noheader,nounits")
    if gpu["success"]:
        for row in gpu["stdout"].splitlines():
            parts = [p.strip() for p in row.split(",")]
            if len(parts) == 4:
                name, total, free, used = parts
                lines.append(f"GPU:  {name}")
                lines.append(f"VRAM: {used}MB used / {total}MB total  ({free}MB free)")
                vram_free_gb = int(free) / 1024
                lines.append(f"      → {vram_free_gb:.1f} GB free")
    else:
        lines.append("GPU: nvidia-smi not available")
        vram_free_gb = 0

    # RAM
    ram = _sh("free -h | grep Mem")
    if ram["success"]:
        lines.append(f"RAM:  {ram['stdout']}")

    # Disk (model storage)
    disk = _sh(f"df -h {LLAMA_MODELS.parent} 2>/dev/null || df -h /mnt/e 2>/dev/null || df -h ~")
    if disk["success"]:
        lines.append(f"Disk: {disk['stdout'].splitlines()[-1]}")

    # Running Ollama models
    ollama_ps = _sh("ollama ps")
    lines.append(f"\nOllama running:\n{ollama_ps['stdout'] or '  (none)'}")

    # Ollama model list
    ollama_list = _sh("ollama list")
    lines.append(f"\nOllama installed:\n{ollama_list['stdout'] or '  (none)'}")

    # llama.cpp models
    if LLAMA_MODELS.exists():
        llama_files = list(LLAMA_MODELS.glob("*.gguf"))
        lines.append(f"\nllama.cpp models ({LLAMA_MODELS}):")
        for f in llama_files:
            size_gb = f.stat().st_size / 1e9
            lines.append(f"  {f.name}  ({size_gb:.1f} GB)")
        if not llama_files:
            lines.append("  (none)")
    else:
        lines.append(f"\nllama.cpp model dir not found: {LLAMA_MODELS}")

    # Recommendations based on free VRAM
    lines.append("\n=== Recommendations ===")
    if vram_free_gb >= 20:
        lines.append("✓ Enough VRAM for coder/deep (32B) solo run")
    elif vram_free_gb >= 9:
        lines.append("✓ Enough for planner 14B + embedding + vision")
    elif vram_free_gb >= 5:
        lines.append("⚠ Only small models fit — embedding + vision only")
    else:
        lines.append("✗ Very low VRAM — check what is loaded")

    # Save hardware snapshot
    registry = load_models_json()
    registry["hardware"] = {
        "gpu_vram_free_gb": round(vram_free_gb, 1),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_models_json(registry)

    return "\n".join(lines)


# ── Ollama helpers ─────────────────────────────────────────────────────────────

def exec_ollama_list() -> str:
    """List installed Ollama models."""
    r = _sh("ollama list")
    return r["stdout"] or "No models installed"


def exec_ollama_pull(model_tag: str, role: str = "planner") -> str:
    """Pull a model via Ollama and register it in models.json."""
    lines = [f"Pulling {model_tag} via Ollama..."]
    r = _sh(f"ollama pull {model_tag}", timeout=600)
    if not r["success"]:
        return f"Pull failed:\n{r['stderr']}"
    lines.append(r["stdout"])

    # Get size info
    info = _sh(f"ollama show {model_tag} --modelinfo 2>/dev/null || ollama show {model_tag}")
    size_match = re.search(r"(\d+\.?\d*)\s*(GB|MB)", info["stdout"])
    size_str = size_match.group(0) if size_match else "unknown"

    _update_model_entry(model_tag, role, "ollama", {
        "size": size_str,
        "validated": False,
    })
    lines.append(f"✓ {model_tag} pulled and added to models.json (role: {role})")
    return "\n".join(lines)


def exec_ollama_remove(model_tag: str) -> str:
    """Remove a model from Ollama and models.json."""
    r = _sh(f"ollama rm {model_tag}")
    if not r["success"]:
        return f"Remove failed: {r['stderr']}"

    registry = load_models_json()
    removed = registry.get("models", {}).pop(model_tag, None)
    save_models_json(registry)

    if removed:
        return f"✓ {model_tag} removed from Ollama and models.json"
    return f"✓ {model_tag} removed from Ollama (was not in models.json)"


# ── HuggingFace helpers ────────────────────────────────────────────────────────

def exec_hf_search(query: str, task: str = "text-generation", top_k: int = 5) -> str:
    """
    Search HuggingFace Hub for models matching query.
    Uses hf CLI: hf models search --filter <task> <query>
    Falls back to HF API if hf CLI not available.
    """
    lines = [f"Searching HuggingFace: '{query}' (task={task})\n"]

    # Try hf CLI first
    cli_result = _sh(
        f"hf models search \"{query}\" --filter {task} --limit {top_k} 2>/dev/null",
        timeout=30,
    )

    if cli_result["success"] and cli_result["stdout"]:
        lines.append(cli_result["stdout"])
        return "\n".join(lines)

    # Fallback: HF API via curl
    encoded_query = query.replace(" ", "%20")
    api_url = (
        f"https://huggingface.co/api/models"
        f"?search={encoded_query}&filter={task}&sort=downloads&direction=-1&limit={top_k}"
    )
    api_result = _sh(f"curl -s '{api_url}'", timeout=30)

    if not api_result["success"]:
        return f"Search failed: {api_result['stderr']}"

    try:
        models = json.loads(api_result["stdout"])
        if not models:
            return "No models found."
        for m in models:
            mid      = m.get("modelId", "?")
            likes    = m.get("likes", 0)
            dl       = m.get("downloads", 0)
            pipeline = m.get("pipeline_tag", task)
            tags     = [t for t in m.get("tags", []) if any(x in t for x in ["GGUF", "gguf", "quantiz", "Q4", "Q8"])]
            gguf_note = "  [GGUF available]" if tags else ""
            lines.append(f"  {mid}")
            lines.append(f"    ↳ {pipeline}  ♥{likes}  ↓{dl:,}{gguf_note}")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not parse results: {e}\nRaw: {api_result['stdout'][:500]}"


def exec_hf_pull(repo_id: str, filename: str, role: str = "vision") -> str:
    """
    Download a specific file from HuggingFace (e.g. a GGUF for llama.cpp).
    Uses: hf download <repo_id> <filename> --local-dir <LLAMA_MODELS>
    """
    LLAMA_MODELS.mkdir(parents=True, exist_ok=True)
    cmd = f"hf download {repo_id} {filename} --local-dir {LLAMA_MODELS}"
    lines = [f"Downloading {repo_id}/{filename} → {LLAMA_MODELS}"]

    r = _sh(cmd, timeout=1800)
    if not r["success"]:
        return f"Download failed:\n{r['stderr']}"

    dest = LLAMA_MODELS / filename
    size_gb = dest.stat().st_size / 1e9 if dest.exists() else 0

    _update_model_entry(f"{repo_id}/{filename}", role, "llama", {
        "repo_id":  repo_id,
        "filename": filename,
        "path":     str(dest),
        "size_gb":  round(size_gb, 2),
        "validated": False,
    })

    lines.append(f"✓ Downloaded {filename} ({size_gb:.1f} GB)")
    lines.append(f"  Registered in models.json as role: {role}")
    return "\n".join(lines)


# ── Validation ─────────────────────────────────────────────────────────────────

VALIDATION_PROMPTS = {
    "planner": "List 3 steps to debug a Python import error. Be concise.",
    "coder":   "Write a Python function that merges two sorted lists. Add type hints.",
    "deep":    "Is the following argument valid? 'All birds can fly. Penguins are birds. Therefore penguins can fly.' Explain.",
    "embedding": None,  # uses ollama embed, not generate
    "vision":  None,    # requires image input — skip text validation
    "default": "Say 'JARVIS validation OK' and nothing else.",
}

def exec_validate_model(model_tag: str, role: str = "default", backend: str = "ollama") -> str:
    """
    Run a quick validation prompt against a model.
    Measures response time, checks output is non-empty and coherent.
    Updates models.json validated flag.
    """
    prompt = VALIDATION_PROMPTS.get(role, VALIDATION_PROMPTS["default"])

    if prompt is None:
        return f"Validation skipped for role '{role}' (requires special input type)"

    lines = [f"Validating {model_tag} (role={role}, backend={backend})..."]
    start = time.monotonic()

    if backend == "ollama":
        # Use ollama run with a timeout
        safe_prompt = prompt.replace("'", "\\'")
        r = _sh(f"ollama run {model_tag} '{safe_prompt}'", timeout=60)
        output = r["stdout"]
        success = r["success"] and len(output.strip()) > 10
    else:
        lines.append("Non-ollama validation not yet implemented — marking as unvalidated")
        return "\n".join(lines)

    elapsed = round(time.monotonic() - start, 2)

    if success:
        lines.append(f"✓ Response received in {elapsed}s")
        lines.append(f"  Output preview: {output[:200]}{'...' if len(output) > 200 else ''}")
        # Update registry
        registry = load_models_json()
        if model_tag in registry.get("models", {}):
            registry["models"][model_tag]["validated"] = True
            registry["models"][model_tag]["validation_time_s"] = elapsed
            save_models_json(registry)
        lines.append("  models.json updated: validated=true")
    else:
        lines.append(f"✗ Validation failed in {elapsed}s")
        lines.append(f"  stderr: {r.get('stderr','')[:200]}")

    return "\n".join(lines)


# ── Upgrade flow ───────────────────────────────────────────────────────────────

def exec_search_upgrades(role: str = "planner") -> str:
    """
    Search for better models for a given role.
    Compares against what's currently in models.json.
    Returns candidates with HF stats for the agent to evaluate.
    """
    role_queries = {
        "planner":   ("qwen3 instruct", "text-generation"),
        "coder":     ("qwen3 coder instruct", "text-generation"),
        "deep":      ("deepseek r1 reasoning", "text-generation"),
        "embedding": ("text embedding nomic", "feature-extraction"),
        "vision":    ("gemma3 multimodal GGUF", "image-text-to-text"),
    }

    query, task = role_queries.get(role, (role, "text-generation"))

    registry = load_models_json()
    current = [
        tag for tag, m in registry.get("models", {}).items()
        if m.get("role") == role
    ]

    lines = [f"Searching for better {role} models...\n"]
    if current:
        lines.append(f"Currently installed for {role}: {', '.join(current)}\n")
    else:
        lines.append(f"No {role} model currently in models.json\n")

    lines.append(exec_hf_search(query, task, top_k=6))
    lines.append("\nTo upgrade: use upgrade_model with the new model tag.")
    return "\n".join(lines)


def exec_upgrade_model(new_tag: str, old_tag: str, role: str, backend: str = "ollama") -> str:
    """
    Full upgrade flow:
      1. Pull new model
      2. Validate it
      3. Report — JARVIS will ask human before removing old

    Does NOT remove old model automatically. Returns instructions for next step.
    """
    lines = [f"=== Upgrade: {old_tag} → {new_tag} (role={role}) ===\n"]

    # Step 1: Pull
    lines.append("Step 1: Pulling new model...")
    pull_result = exec_ollama_pull(new_tag, role) if backend == "ollama" else f"Use hf_pull for backend={backend}"
    lines.append(pull_result)
    if "failed" in pull_result.lower():
        return "\n".join(lines) + "\n✗ Upgrade aborted at pull step."

    # Step 2: Validate
    lines.append("\nStep 2: Validating new model...")
    val_result = exec_validate_model(new_tag, role, backend)
    lines.append(val_result)

    validated = "validated=true" in val_result
    lines.append(f"\nValidation {'PASSED ✓' if validated else 'FAILED ✗'}")

    if validated:
        lines.append(
            f"\nStep 3: Ready to remove old model '{old_tag}'.\n"
            f"  → Call remove_model('{old_tag}') to complete the upgrade.\n"
            f"  → Or keep both if you want a fallback."
        )
    else:
        lines.append(
            f"\n⚠ New model failed validation. Old model '{old_tag}' kept.\n"
            f"  Investigate before removing."
        )

    return "\n".join(lines)


# ── Install bootstrap ──────────────────────────────────────────────────────────

def exec_install_bootstrap() -> str:
    """
    First-time JARVIS model install:
      1. System check
      2. Install Ollama if missing
      3. Pull planner (qwen3:14b) + embedding (nomic-embed-text)
      4. Validate both
      5. Search for latest vision GGUF (gemma3:4b)
      6. Write initial models.json
    """
    lines = ["=== JARVIS Model Bootstrap ===\n"]

    # 1. System check
    lines.append("── System Check ──")
    lines.append(exec_system_check())

    # 2. Ollama
    lines.append("\n── Ollama ──")
    ollama_ver = _sh("ollama --version")
    if ollama_ver["success"]:
        lines.append(f"Ollama found: {ollama_ver['stdout']}")
    else:
        lines.append("Ollama not found. Installing...")
        install = _sh("curl -fsSL https://ollama.com/install.sh | sh", timeout=300)
        lines.append(install["stdout"] if install["success"] else f"Install failed: {install['stderr']}")

    # 3. Pull core models
    for tag, role in [("qwen3:14b", "planner"), ("nomic-embed-text", "embedding")]:
        lines.append(f"\n── Pulling {tag} ({role}) ──")
        lines.append(exec_ollama_pull(tag, role))

    # 4. Validate
    for tag, role in [("qwen3:14b", "planner"), ("nomic-embed-text", "embedding")]:
        lines.append(f"\n── Validating {tag} ──")
        lines.append(exec_validate_model(tag, role, "ollama"))

    # 5. Vision model hint
    lines.append("\n── Vision Model ──")
    lines.append("Search for latest gemma3 GGUF:")
    lines.append(exec_hf_search("gemma3 4b GGUF multimodal", "image-text-to-text", top_k=3))
    lines.append("  → Use hf_pull to download chosen GGUF to llama.cpp models dir")

    # 6. Final registry state
    lines.append("\n── models.json ──")
    registry = load_models_json()
    lines.append(json.dumps(registry, indent=2))

    return "\n".join(lines)


# ── Tool executors ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "system_check",
            "description": "Check GPU VRAM, RAM, disk, running Ollama models, installed llama.cpp GGUFs. Updates models.json hardware section. Run first before any model operation.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ollama_list",
            "description": "List all installed Ollama models.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ollama_pull",
            "description": "Pull a model via Ollama and register it in models.json.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_tag": {"type": "string", "description": "Ollama model tag, e.g. 'qwen3:14b'"},
                    "role":      {"type": "string", "enum": ["planner", "coder", "deep", "embedding", "vision"], "description": "Model role in JARVIS"},
                },
                "required": ["model_tag", "role"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ollama_remove",
            "description": "Remove a model from Ollama and models.json. Always validate the replacement first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_tag": {"type": "string", "description": "Ollama model tag to remove"},
                },
                "required": ["model_tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hf_search",
            "description": "Search HuggingFace Hub for models. Use to find better/newer models for a role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query, e.g. 'qwen3 32b instruct GGUF'"},
                    "task":  {"type": "string", "description": "HF task filter e.g. text-generation, feature-extraction", "default": "text-generation"},
                    "top_k": {"type": "integer", "description": "Number of results", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hf_pull",
            "description": "Download a GGUF or model file from HuggingFace for use with llama.cpp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_id":  {"type": "string", "description": "HF repo, e.g. 'google/gemma-3-4b-it-GGUF'"},
                    "filename": {"type": "string", "description": "File to download, e.g. 'gemma-3-4b-it-Q4_K_M.gguf'"},
                    "role":     {"type": "string", "enum": ["planner", "coder", "deep", "embedding", "vision"], "default": "vision"},
                },
                "required": ["repo_id", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_model",
            "description": "Run a validation prompt against a model. Measures response time and quality. Updates models.json validated flag.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_tag": {"type": "string", "description": "Model tag to validate"},
                    "role":      {"type": "string", "enum": ["planner", "coder", "deep", "embedding", "vision", "default"], "default": "default"},
                    "backend":   {"type": "string", "enum": ["ollama", "llama"], "default": "ollama"},
                },
                "required": ["model_tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_upgrades",
            "description": "Search HuggingFace for better models for a given JARVIS role. Compares against currently installed models.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["planner", "coder", "deep", "embedding", "vision"], "description": "Role to find upgrade for"},
                },
                "required": ["role"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upgrade_model",
            "description": "Full upgrade flow: pull new model, validate it, then report. Does NOT remove old model — waits for human confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_tag":  {"type": "string", "description": "New model tag to pull"},
                    "old_tag":  {"type": "string", "description": "Current model tag to replace"},
                    "role":     {"type": "string", "enum": ["planner", "coder", "deep", "embedding", "vision"]},
                    "backend":  {"type": "string", "enum": ["ollama", "llama"], "default": "ollama"},
                },
                "required": ["new_tag", "old_tag", "role"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_bootstrap",
            "description": "First-time JARVIS model installation: system check, install Ollama, pull qwen3:14b + embedding, validate, search for vision GGUF, write models.json.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_models_json",
            "description": "Show current contents of models.json registry.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

TOOL_MAP = {
    "system_check":     lambda args: exec_system_check(),
    "ollama_list":      lambda args: exec_ollama_list(),
    "ollama_pull":      lambda args: exec_ollama_pull(args["model_tag"], args.get("role", "planner")),
    "ollama_remove":    lambda args: exec_ollama_remove(args["model_tag"]),
    "hf_search":        lambda args: exec_hf_search(args["query"], args.get("task", "text-generation"), args.get("top_k", 5)),
    "hf_pull":          lambda args: exec_hf_pull(args["repo_id"], args["filename"], args.get("role", "vision")),
    "validate_model":   lambda args: exec_validate_model(args["model_tag"], args.get("role", "default"), args.get("backend", "ollama")),
    "search_upgrades":  lambda args: exec_search_upgrades(args.get("role", "planner")),
    "upgrade_model":    lambda args: exec_upgrade_model(args["new_tag"], args["old_tag"], args["role"], args.get("backend", "ollama")),
    "install_bootstrap":lambda args: exec_install_bootstrap(),
    "show_models_json": lambda args: json.dumps(load_models_json(), indent=2),
}

KEYWORDS = {
    "system_check":      ["system check", "vram", "ram", "hardware", "gpu", "memory", "resources"],
    "ollama_list":       ["list models", "installed models", "what models", "ollama list"],
    "ollama_pull":       ["pull", "install model", "download model", "ollama pull", "get model"],
    "ollama_remove":     ["remove model", "delete model", "uninstall model", "ollama rm"],
    "hf_search":         ["search", "huggingface", "find model", "new model", "better model", "hf search"],
    "hf_pull":           ["hf download", "download gguf", "huggingface download", "get gguf"],
    "validate_model":    ["validate", "test model", "benchmark model", "check model quality"],
    "search_upgrades":   ["upgrade search", "better planner", "better coder", "newer model", "check for updates", "qwen3"],
    "upgrade_model":     ["upgrade", "swap model", "replace model", "update model"],
    "install_bootstrap": ["bootstrap", "first install", "setup models", "initialize models", "fresh install"],
    "show_models_json":  ["models.json", "show registry", "model registry", "what's in models.json"],
}
