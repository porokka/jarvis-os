from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_CONFIG_PATH = PROJECT_ROOT / "config/models-config.json"
VAULT_DIR = Path("D:/Jarvis_vault")

DEFAULT_MODELS = {
    "fast": "qwen3:8b",
    "tools": "qwen3:14b",
    "reason": "qwen3:14b",
    "code": "qwen3-coder:14b",
    "deep": "qwen3:30b-a3b",
}

DEFAULT_PLANNER_MODEL = "qwen3:14b"

_CONFIG_CACHE: Dict[str, Any] = {}
_CONFIG_CACHE_MTIME: Optional[float] = None


def ensure_dirs() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)


def append_log(line: str) -> None:
    try:
        ensure_dirs()
        with open(VAULT_DIR / "jarvis.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_model_config(force: bool = False) -> Dict[str, Any]:
    global _CONFIG_CACHE, _CONFIG_CACHE_MTIME

    try:
        if not MODEL_CONFIG_PATH.exists():
            if force or _CONFIG_CACHE != {}:
                append_log(f"[MODEL_CONFIG] File not found: {MODEL_CONFIG_PATH}")
            _CONFIG_CACHE = {}
            _CONFIG_CACHE_MTIME = None
            return {}

        mtime = MODEL_CONFIG_PATH.stat().st_mtime

        if not force and _CONFIG_CACHE_MTIME == mtime and _CONFIG_CACHE:
            return _CONFIG_CACHE

        raw = MODEL_CONFIG_PATH.read_text(encoding="utf-8")
        cfg = json.loads(raw)

        if not isinstance(cfg, dict):
            append_log("[MODEL_CONFIG] Invalid config format, expected object")
            _CONFIG_CACHE = {}
            _CONFIG_CACHE_MTIME = mtime
            return {}

        _CONFIG_CACHE = cfg
        _CONFIG_CACHE_MTIME = mtime

        append_log("[MODEL_CONFIG] Loaded config successfully")
        append_log(f"[MODEL_CONFIG] Models: {cfg.get('models', {})}")
        append_log(f"[MODEL_CONFIG] Planner: {cfg.get('planner_model')}")

        return cfg

    except Exception as e:
        append_log(f"[MODEL_CONFIG] ERROR loading config: {e}")
        return {}


def get_models(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    cfg = cfg or load_model_config()
    models = cfg.get("models", {})
    if not isinstance(models, dict):
        models = {}

    return {
        key: str(models.get(key, default))
        for key, default in DEFAULT_MODELS.items()
    }


def get_skill_models(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    cfg = cfg or load_model_config()
    skill_models = cfg.get("skill_models", {})
    if not isinstance(skill_models, dict):
        return {}
    return {str(k): str(v) for k, v in skill_models.items()}


def get_planner_model(cfg: Optional[Dict[str, Any]] = None) -> str:
    cfg = cfg or load_model_config()
    return str(cfg.get("planner_model", DEFAULT_PLANNER_MODEL))


def get_model_for_route(route: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    return get_models(cfg).get(route, DEFAULT_MODELS["reason"])


def get_model_for_skill(skill_name: str, fallback_route: str = "reason", cfg: Optional[Dict[str, Any]] = None) -> str:
    skill_models = get_skill_models(cfg)
    if skill_name in skill_models:
        return skill_models[skill_name]
    return get_model_for_route(fallback_route, cfg)


def resolve_model(
    requested_model: Optional[str] = None,
    route: Optional[str] = None,
    skill_name: Optional[str] = None,
) -> str:
    cfg = load_model_config()

    append_log(
        f"[MODEL_RESOLVE] requested={requested_model} route={route} skill={skill_name}"
    )

    if requested_model:
        append_log(f"[MODEL_RESOLVE] Using requested_model={requested_model}")
        return requested_model

    if skill_name:
        model = get_model_for_skill(skill_name, fallback_route=route or "reason", cfg=cfg)
        append_log(f"[MODEL_RESOLVE] Using skill model={model}")
        return model

    if route:
        model = get_model_for_route(route, cfg=cfg)
        append_log(f"[MODEL_RESOLVE] Using route model={model}")
        return model

    model = get_model_for_route("reason", cfg=cfg)
    append_log(f"[MODEL_RESOLVE] Using default model={model}")
    return model