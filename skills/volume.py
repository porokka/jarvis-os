"""
JARVIS Skill — Windows system volume control via PowerShell COM API.
"""

import subprocess

SKILL_NAME = "volume"
SKILL_DESCRIPTION = "Windows master volume control (0-100%)"

PS_VOLUME_SCRIPT = """
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {{
    int _0(); int _1(); int _2(); int _3();
    int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
    int GetMasterVolumeLevelScalar(out float pfLevel);
}}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {{ int Activate(ref System.Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface); }}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {{ int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice); }}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {{}}
public class Vol {{
    public static void Set(float v) {{
        var e = new MMDeviceEnumerator() as IMMDeviceEnumerator;
        IMMDevice d; e.GetDefaultAudioEndpoint(0, 1, out d);
        var iid = typeof(IAudioEndpointVolume).GUID;
        object o; d.Activate(ref iid, 1, IntPtr.Zero, out o);
        (o as IAudioEndpointVolume).SetMasterVolumeLevelScalar(v, Guid.Empty);
    }}
}}
'@
[Vol]::Set({level})
"""


def exec_set_volume(level: float) -> str:
    level = max(0, min(100, int(level)))
    try:
        result = subprocess.run(
            ['powershell.exe', '-Command', PS_VOLUME_SCRIPT.format(level=level / 100.0)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return f"Volume set to {level}%"
        return f"Volume error: {result.stderr[:100]}"
    except Exception as e:
        return f"Volume error: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Set the system volume. 0-100 percent. Use when asked to turn up, turn down, mute, or set volume.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "number",
                        "description": "Volume level 0-100. Use 0 for mute.",
                    }
                },
                "required": ["level"],
            },
        },
    },
]

TOOL_MAP = {"set_volume": exec_set_volume}

KEYWORDS = {
    "set_volume": ["volume", "louder", "quieter", "turn up", "turn down", "mute", "unmute", "loud", "quiet"],
}
