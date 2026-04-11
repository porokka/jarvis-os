# System Volume Skill

Controls Windows master volume via the Windows Audio COM API (PowerShell).

**File:** `skills/volume.py`

---

## Prerequisites

- Windows with PowerShell
- No additional installs needed

---

## Tools

### set_volume

Set the system master volume level.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `level` | number | yes | Volume percentage, 0-100. Use 0 for mute. |

**Examples:**
```
"Set volume to 50%"
"Turn it down to 20"
"Mute the volume"          → set_volume(0)
"Turn the volume up to 80"
```

---

## Notes

- This controls **Windows master volume**, not the Denon receiver
- For Denon volume, use the `denon_volume` tool
- Uses COM interop via PowerShell — works on all Windows 10/11 systems
