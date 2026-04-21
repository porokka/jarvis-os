"""
JARVIS Skill — Windows system volume control via PowerShell COM API.
"""

import os
import subprocess
from typing import Optional


SKILL_NAME = "volume"
SKILL_DESCRIPTION = "Windows master volume control (0-100%)"
SKILL_VERSION = "1.2.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "system"
SKILL_TAGS = ["windows", "volume", "audio", "mute", "sound", "powershell", "memory"]
SKILL_REQUIREMENTS = ["Windows", "powershell.exe"]
SKILL_CAPABILITIES = [
    "set_volume",
    "get_volume",
    "mute_volume",
    "unmute_volume",
    "memory_integration",
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
    "writes_files": False,
    "reads_files": False,
    "network_access": False,
    "entrypoint": "exec_volume",
}


_LAST_NONZERO_VOLUME = 50


# -- Memory helpers --

def _memory_call(action: str, key: str = "", value: str = "", event_type: str = "", data: dict = None, query: str = ""):
    """
    Best-effort bridge to memory skill.
    Returns None if memory skill is unavailable or errors.
    """
    try:
        from skills.memory import exec_memory
        return exec_memory(
            action=action,
            key=key,
            value=value,
            event_type=event_type,
            data=data,
            query=query,
        )
    except Exception:
        return None


def _remember_preference(key: str, value: str) -> None:
    _memory_call("set_preference", key=key, value=value)


def _remember_recent(key: str, value: str) -> None:
    _memory_call("set_recent", key=key, value=value)


def _log_memory_event(event_type: str, data: dict) -> None:
    _memory_call("log_event", event_type=event_type, data=data or {})


def _get_memory_preference(key: str) -> Optional[str]:
    try:
        from skills.memory import _load_state  # type: ignore
        state = _load_state()
        value = state.get("identity", {}).get(key)
        return str(value) if value is not None else None
    except Exception:
        return None


def _get_memory_recent(key: str) -> Optional[str]:
    try:
        from skills.memory import _load_state  # type: ignore
        state = _load_state()
        value = state.get("recent", {}).get(key)
        return str(value) if value is not None else None
    except Exception:
        return None


PS_VOLUME_LIB = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    int _0(); int _1(); int _2(); int _3();
    int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
    int GetMasterVolumeLevelScalar(out float pfLevel);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref System.Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice);
}

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumerator {}

public class Vol {
    public static IAudioEndpointVolume GetEndpoint() {
        var e = new MMDeviceEnumerator() as IMMDeviceEnumerator;
        IMMDevice d;
        e.GetDefaultAudioEndpoint(0, 1, out d);
        var iid = typeof(IAudioEndpointVolume).GUID;
        object o;
        d.Activate(ref iid, 1, IntPtr.Zero, out o);
        return (IAudioEndpointVolume)o;
    }

    public static void Set(float v) {
        GetEndpoint().SetMasterVolumeLevelScalar(v, Guid.Empty);
    }

    public static float Get() {
        float level;
        GetEndpoint().GetMasterVolumeLevelScalar(out level);
        return level;
    }
}
'@
"""


def _is_windows() -> bool:
    return os.name == "nt"


def _run_powershell(script: str) -> tuple[bool, str]:
    if not _is_windows():
        return False, "Volume control is only supported on Windows."

    try:
        result = subprocess.run(
            ["powershell.exe", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, (result.stdout or "").strip()
        return False, ((result.stderr or result.stdout) or "Unknown PowerShell error").strip()[:300]
    except Exception as e:
        return False, str(e)


def _set_volume_scalar(level_scalar: float) -> tuple[bool, str]:
    level_scalar = max(0.0, min(1.0, float(level_scalar)))
    script = PS_VOLUME_LIB + f"\n[Vol]::Set({level_scalar})\n"
    return _run_powershell(script)


def _get_volume_percent() -> tuple[bool, Optional[int], str]:
    script = PS_VOLUME_LIB + "\n[Console]::WriteLine([int]([Math]::Round(([Vol]::Get() * 100))))\n"
    ok, output = _run_powershell(script)
    if not ok:
        return False, None, output

    try:
        value = int((output or "").splitlines()[-1].strip())
        value = max(0, min(100, value))
        return True, value, ""
    except Exception:
        return False, None, f"Failed to parse current volume: {output}"


def _resolve_unmute_level() -> int:
    """
    Prefer remembered last non-zero volume if available.
    """
    remembered = _get_memory_recent("last_nonzero_volume")
    if remembered is not None:
        try:
            return max(1, min(100, int(float(remembered))))
        except Exception:
            pass

    remembered_pref = _get_memory_preference("preferred_volume")
    if remembered_pref is not None:
        try:
            return max(1, min(100, int(float(remembered_pref))))
        except Exception:
            pass

    return max(1, min(100, int(_LAST_NONZERO_VOLUME or 50)))


def exec_volume(action: str, level: float = 0) -> str:
    global _LAST_NONZERO_VOLUME

    action = (action or "").strip().lower()

    if action == "get":
        ok, value, err = _get_volume_percent()
        if not ok:
            return f"Volume error: {err}"

        _remember_recent("last_volume", str(value))
        _remember_recent("last_volume_action", "get")
        _log_memory_event(
            "volume_checked",
            {
                "volume": value,
            },
        )
        return f"Current volume: {value}%"

    if action == "set":
        try:
            level_int = int(float(level))
        except Exception:
            return "Volume error: level must be a number"

        level_int = max(0, min(100, level_int))
        ok, err = _set_volume_scalar(level_int / 100.0)
        if not ok:
            return f"Volume error: {err}"

        if level_int > 0:
            _LAST_NONZERO_VOLUME = level_int
            _remember_recent("last_nonzero_volume", str(level_int))
            _remember_preference("preferred_volume", str(level_int))

        _remember_recent("last_volume", str(level_int))
        _remember_recent("last_volume_action", "set")
        _log_memory_event(
            "volume_set",
            {
                "volume": level_int,
            },
        )
        return f"Volume set to {level_int}%"

    if action == "mute":
        ok, current, err = _get_volume_percent()
        if ok and current is not None and current > 0:
            _LAST_NONZERO_VOLUME = current
            _remember_recent("last_nonzero_volume", str(current))

        ok, err = _set_volume_scalar(0.0)
        if not ok:
            return f"Volume error: {err}"

        _remember_recent("last_volume", "0")
        _remember_recent("last_volume_action", "mute")
        _log_memory_event(
            "volume_muted",
            {
                "previous_volume": current if current is not None else "",
            },
        )
        return "Volume muted."

    if action == "unmute":
        restore = _resolve_unmute_level()
        ok, err = _set_volume_scalar(restore / 100.0)
        if not ok:
            return f"Volume error: {err}"

        _LAST_NONZERO_VOLUME = restore
        _remember_recent("last_nonzero_volume", str(restore))
        _remember_recent("last_volume", str(restore))
        _remember_recent("last_volume_action", "unmute")
        _remember_preference("preferred_volume", str(restore))
        _log_memory_event(
            "volume_unmuted",
            {
                "restored_volume": restore,
            },
        )
        return f"Volume restored to {restore}%"

    return "Available actions: get, set, mute, unmute"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "volume",
            "description": (
                "Control Windows master volume with memory. "
                "Actions: get, set, mute, unmute. Remembers last non-zero volume and preferred volume."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set", "mute", "unmute"],
                        "description": "Volume action to perform.",
                    },
                    "level": {
                        "type": "number",
                        "description": "Volume level 0-100 for action=set.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "volume": exec_volume,
}

KEYWORDS = {
    "volume": [
        "volume",
        "louder",
        "quieter",
        "turn up",
        "turn down",
        "mute",
        "unmute",
        "loud",
        "quiet",
        "sound",
        "audio",
    ],
}

SKILL_EXAMPLES = [
    {"command": "set volume to 30 percent", "tool": "volume", "args": {"action": "set", "level": 30}},
    {"command": "mute sound", "tool": "volume", "args": {"action": "mute"}},
    {"command": "unmute sound", "tool": "volume", "args": {"action": "unmute"}},
    {"command": "what is the volume", "tool": "volume", "args": {"action": "get"}},
]