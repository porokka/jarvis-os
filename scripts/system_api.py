#!/usr/bin/env python3
"""
JARVIS OS — System API Server
FastAPI backend for the Next.js web UI.
Handles: GPU stats, Ollama model management, apt packages,
         service control, file uploads, vault/code sync.

Run: uvicorn system_api:app --host 0.0.0.0 --port 7800
"""

import os, subprocess, shutil, json, asyncio, time
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import zipfile, tempfile

# ── Config ────────────────────────────────────────────────────
JARVIS_DIR   = Path(os.environ.get("JARVIS_DIR", Path.home() / "jarvis-os"))
VAULT_DIR    = JARVIS_DIR / "vault"
CODE_DIR     = Path(os.environ.get("CODE_DIR", Path.home() / "code"))
AUDIT_LOG    = JARVIS_DIR / "vault" / "system" / "audit.log"
API_TOKEN    = os.environ.get("JARVIS_API_TOKEN", "jarvis-local-token")

# Whitelisted apt packages (extend as needed)
ALLOWED_APT = {
    "curl", "git", "python3", "python3-pip", "nodejs", "npm",
    "ffmpeg", "espeak", "aplay", "htop", "nvtop", "build-essential",
    "piper", "whisper", "nvidia-cuda-toolkit"
}

# Whitelisted pip packages
ALLOWED_PIP = {
    "ollama", "fastapi", "uvicorn", "whisper", "openai-whisper",
    "sounddevice", "soundfile", "numpy", "torch", "transformers",
    "requests", "httpx", "pydantic", "python-multipart"
}

# Whitelisted systemd services
ALLOWED_SERVICES = {
    "jarvis-watcher", "jarvis-api", "ollama",
    "jarvis-nextjs", "jarvis-bridge"
}

app = FastAPI(title="JARVIS OS System API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────
def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization or authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

def audit(action: str, detail: str = ""):
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {action}: {detail}\n")

def run_cmd(cmd: list, timeout: int = 120) -> dict:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timeout", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}

# ── GPU Stats ─────────────────────────────────────────────────
@app.get("/api/gpu/stats")
async def gpu_stats():
    result = run_cmd([
        "nvidia-smi",
        "--query-gpu=index,name,temperature.gpu,utilization.gpu,"
        "memory.used,memory.total,power.draw,power.limit",
        "--format=csv,noheader,nounits"
    ])
    gpus = []
    if result["success"]:
        for line in result["stdout"].splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 8:
                gpus.append({
                    "index":       int(parts[0]),
                    "name":        parts[1],
                    "temp":        float(parts[2]),
                    "utilization": float(parts[3]),
                    "vram_used":   float(parts[4]),
                    "vram_total":  float(parts[5]),
                    "power_draw":  float(parts[6]) if parts[6] != "[N/A]" else 0,
                    "power_limit": float(parts[7]) if parts[7] != "[N/A]" else 0,
                })
    return {"gpus": gpus}

# ── System Stats ──────────────────────────────────────────────
@app.get("/api/system/stats")
async def system_stats():
    cpu = run_cmd(["top", "-bn1"])
    mem = run_cmd(["free", "-m"])
    disk = run_cmd(["df", "-h", "/"])
    uptime = run_cmd(["uptime", "-p"])
    return {
        "uptime": uptime.get("stdout", ""),
        "memory": mem.get("stdout", ""),
        "disk":   disk.get("stdout", ""),
    }

# ── Ollama Model Management ───────────────────────────────────
@app.get("/api/ollama/models")
async def list_models():
    result = run_cmd(["ollama", "list"])
    models = []
    if result["success"]:
        lines = result["stdout"].splitlines()[1:]  # skip header
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                models.append({
                    "name": parts[0],
                    "id":   parts[1],
                    "size": parts[2] + " " + parts[3],
                })
    return {"models": models}

class ModelRequest(BaseModel):
    model: str
    gpu: Optional[int] = 0

@app.post("/api/ollama/pull")
async def pull_model(req: ModelRequest, authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    audit("ollama_pull", req.model)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(req.gpu)
    result = run_cmd(["ollama", "pull", req.model], timeout=600)
    return result

@app.delete("/api/ollama/models/{model_name}")
async def delete_model(model_name: str, authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    audit("ollama_delete", model_name)
    result = run_cmd(["ollama", "rm", model_name])
    return result

@app.post("/api/ollama/assign-gpu")
async def assign_gpu(req: ModelRequest, authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    audit("ollama_assign_gpu", f"{req.model} → GPU {req.gpu}")
    env_file = JARVIS_DIR / ".env"
    lines = []
    if env_file.exists():
        lines = env_file.read_text().splitlines()
    key = f"GPU_{req.model.replace(':', '_').replace('.', '_').upper()}"
    lines = [l for l in lines if not l.startswith(key)]
    lines.append(f"{key}={req.gpu}")
    env_file.write_text("\n".join(lines))
    return {"success": True, "message": f"{req.model} assigned to GPU {req.gpu}"}

# ── Package Management ────────────────────────────────────────
class PackageRequest(BaseModel):
    package: str
    manager: str  # apt | pip | npm

@app.post("/api/packages/install")
async def install_package(req: PackageRequest, authorization: Optional[str] = Header(None)):
    verify_token(authorization)

    if req.manager == "apt":
        if req.package not in ALLOWED_APT:
            raise HTTPException(400, f"Package '{req.package}' not in allowlist")
        cmd = ["sudo", "apt", "install", "-y", req.package]
    elif req.manager == "pip":
        if req.package not in ALLOWED_PIP:
            raise HTTPException(400, f"Package '{req.package}' not in allowlist")
        cmd = ["pip3", "install", req.package]
    elif req.manager == "npm":
        cmd = ["npm", "install", "-g", req.package]
    else:
        raise HTTPException(400, "Unknown package manager")

    audit("package_install", f"{req.manager}:{req.package}")
    result = run_cmd(cmd, timeout=300)
    return result

@app.post("/api/packages/upgrade")
async def upgrade_packages(authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    audit("system_upgrade", "apt upgrade")
    result = run_cmd(["sudo", "apt", "upgrade", "-y"], timeout=600)
    return result

# ── Service Management ────────────────────────────────────────
class ServiceRequest(BaseModel):
    service: str
    action: str  # start | stop | restart | status

@app.post("/api/services/control")
async def service_control(req: ServiceRequest, authorization: Optional[str] = Header(None)):
    verify_token(authorization)
    if req.service not in ALLOWED_SERVICES:
        raise HTTPException(400, f"Service '{req.service}' not in allowlist")
    if req.action not in ["start", "stop", "restart", "status"]:
        raise HTTPException(400, "Invalid action")
    audit("service_control", f"{req.action} {req.service}")
    result = run_cmd(["sudo", "systemctl", req.action, req.service])
    return result

@app.get("/api/services/status")
async def all_service_status():
    statuses = {}
    for service in ALLOWED_SERVICES:
        result = run_cmd(["systemctl", "is-active", service])
        statuses[service] = result.get("stdout", "unknown")
    return statuses

# ── JARVIS File Bridge ────────────────────────────────────────
@app.get("/api/jarvis/state")
async def jarvis_state():
    state_file = JARVIS_DIR / "state.txt"
    output_file = JARVIS_DIR / "output.txt"
    brain_file = JARVIS_DIR / "brain.txt"
    return {
        "state":  state_file.read_text().strip() if state_file.exists() else "standby",
        "output": output_file.read_text().strip() if output_file.exists() else "",
        "brain":  brain_file.read_text().strip() if brain_file.exists() else "",
    }

@app.post("/api/jarvis/command")
async def jarvis_command(authorization: Optional[str] = Header(None), body: dict = {}):
    verify_token(authorization)
    command = body.get("command", "").strip()
    if not command:
        raise HTTPException(400, "Empty command")
    input_file = JARVIS_DIR / "input.txt"
    input_file.write_text(command)
    audit("jarvis_command", command[:100])
    return {"success": True}

# ── Vault Upload ──────────────────────────────────────────────
@app.post("/api/upload/vault")
async def upload_vault(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    verify_token(authorization)
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Only .zip files accepted")

    audit("vault_upload", file.filename)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "vault.zip"
        zip_path.write_bytes(await file.read())

        with zipfile.ZipFile(zip_path, "r") as z:
            # Safety check — no path traversal
            for name in z.namelist():
                if ".." in name or name.startswith("/"):
                    raise HTTPException(400, "Invalid zip contents")
            z.extractall(tmp)

        # Merge into vault dir (don't wipe, just update)
        extracted = [p for p in Path(tmp).iterdir() if p.is_dir() and p.name != "__MACOSX"]
        src = extracted[0] if extracted else Path(tmp)

        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            if item.is_file():
                dest = VAULT_DIR / item.relative_to(src)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)

    return {"success": True, "message": f"Vault synced from {file.filename}"}

# ── Code Directory Upload ─────────────────────────────────────
@app.post("/api/upload/code")
async def upload_code(
    file: UploadFile = File(...),
    project: str = Form(...),
    authorization: Optional[str] = Header(None)
):
    verify_token(authorization)
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Only .zip files accepted")

    audit("code_upload", f"{project}: {file.filename}")

    project_dir = CODE_DIR / project
    project_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "code.zip"
        zip_path.write_bytes(await file.read())

        with zipfile.ZipFile(zip_path, "r") as z:
            for name in z.namelist():
                if ".." in name or name.startswith("/"):
                    raise HTTPException(400, "Invalid zip contents")
            z.extractall(tmp)

        extracted = [p for p in Path(tmp).iterdir() if p.is_dir() and p.name != "__MACOSX"]
        src = extracted[0] if extracted else Path(tmp)

        for item in src.rglob("*"):
            if item.is_file():
                dest = project_dir / item.relative_to(src)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)

    return {"success": True, "message": f"Code uploaded to {project_dir}"}

# ── Vault File Browser ────────────────────────────────────────
@app.get("/api/vault/files")
async def vault_files(path: str = ""):
    target = VAULT_DIR / path if path else VAULT_DIR
    if not target.exists():
        return {"files": [], "dirs": []}
    files = [f.name for f in target.iterdir() if f.is_file()]
    dirs  = [d.name for d in target.iterdir() if d.is_dir()]
    return {"files": sorted(files), "dirs": sorted(dirs), "path": path}

@app.get("/api/vault/read")
async def vault_read(path: str):
    target = VAULT_DIR / path
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "File not found")
    if target.suffix not in [".md", ".txt", ".json", ".sh", ".py", ".jsx", ".ts"]:
        raise HTTPException(400, "File type not readable")
    return {"content": target.read_text(), "path": path}

@app.put("/api/vault/write")
async def vault_write(
    path: str,
    body: dict = {},
    authorization: Optional[str] = Header(None)
):
    verify_token(authorization)
    target = VAULT_DIR / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.get("content", ""))
    audit("vault_write", path)
    return {"success": True}

# ── Audit Log ─────────────────────────────────────────────────
@app.get("/api/system/audit")
async def get_audit_log(lines: int = 50):
    if not AUDIT_LOG.exists():
        return {"log": []}
    all_lines = AUDIT_LOG.read_text().splitlines()
    return {"log": all_lines[-lines:]}

if __name__ == "__main__":
    import uvicorn
    cert_dir = JARVIS_DIR / "certs"
    ssl_args = {}
    if (cert_dir / "jarvis.crt").exists() and (cert_dir / "jarvis.key").exists():
        ssl_args = {"ssl_certfile": str(cert_dir / "jarvis.crt"), "ssl_keyfile": str(cert_dir / "jarvis.key")}
    uvicorn.run(app, host="0.0.0.0", port=7800, reload=False, **ssl_args)
