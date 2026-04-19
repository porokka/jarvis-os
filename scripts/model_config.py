from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_CONFIG_PATH = PROJECT_ROOT / "config/models-config.json"

DEFAULT_MODELS = {
    "fast": "qwen3:8b",
    "reason": "qwen3:14b",
    "code": "qwen3-coder:14b",
    "deep": "qwen3:30b-a3b",
}

DEFAULT_PLANNER_MODEL = "qwen3:14b"
def append_log(line: str) -> None:
    try:
        ensure_dirs()
        with open(VAULT_DIR / "jarvis.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    

def load_model_config() -> Dict[str, Any]:
    if not MODEL_CONFIG_PATH.exists():
        append_log(f"[MODEL_CONFIG] File not found: {MODEL_CONFIG_PATH}")
        return {}

    try:
        raw = MODEL_CONFIG_PATH.read_text(encoding="utf-8")
        cfg = json.loads(raw)

        append_log(f"[MODEL_CONFIG] Loaded config successfully")
        append_log(f"[MODEL_CONFIG] Models: {cfg.get('models', {})}")
        append_log(f"[MODEL_CONFIG] Planner: {cfg.get('planner_model')}")

        return cfg

    except Exception as e:
        append_log(f"[MODEL_CONFIG] ERROR loading config: {e}")
        return {}


def get_models() -> Dict[str, str]:
    cfg = load_model_config()
    models = cfg.get("models", {})
    return {
        key: str(models.get(key, default))
        for key, default in DEFAULT_MODELS.items()
    }


def get_skill_models() -> Dict[str, str]:
    cfg = load_model_config()
    skill_models = cfg.get("skill_models", {})
    return {str(k): str(v) for k, v in skill_models.items()}


def get_planner_model() -> str:
    cfg = load_model_config()
    return str(cfg.get("planner_model", DEFAULT_PLANNER_MODEL))


def get_model_for_route(route: str) -> str:
    return get_models().get(route, DEFAULT_MODELS["reason"])


def get_model_for_skill(skill_name: str, fallback_route: str = "reason") -> str:
    skill_models = get_skill_models()
    if skill_name in skill_models:
        return skill_models[skill_name]
    return get_model_for_route(fallback_route)


def resolve_model(
    requested_model: Optional[str] = None,
    route: Optional[str] = None,
    skill_name: Optional[str] = None,
) -> str:
    append_log(
        f"[MODEL_RESOLVE] requested={requested_model} route={route} skill={skill_name}"
    )

    if requested_model:
        append_log(f"[MODEL_RESOLVE] Using requested_model={requested_model}")
        return requested_model

    if skill_name:
        model = get_model_for_skill(skill_name, fallback_route=route or "reason")
        append_log(f"[MODEL_RESOLVE] Using skill model={model}")
        return model

    if route:
        model = get_model_for_route(route)
        append_log(f"[MODEL_RESOLVE] Using route model={model}")
        return model

    model = get_model_for_route("reason")
    append_log(f"[MODEL_RESOLVE] Using default model={model}")
    return model