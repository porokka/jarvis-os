"""
JARVIS Skill — LG webOS TV control.

Controls LG OLED65E6V via WebSocket API.
First run requires pairing — accept the prompt on the TV.
Client key is saved to config/lg_tv_key.json.
"""

import asyncio
import json
from pathlib import Path

SKILL_NAME = "lg_tv"
SKILL_DESCRIPTION = "LG webOS TV — power, volume, input, apps, media control"

CONFIG_DIR = Path(__file__).parent.parent / "config"
KEY_FILE = CONFIG_DIR / "lg_tv_key.json"
TV_CONFIG = CONFIG_DIR / "lg_tv.json"


def _get_tv_ip() -> str:
    try:
        data = json.loads(TV_CONFIG.read_text(encoding="utf-8"))
        return data.get("ip", "")
    except Exception:
        return ""


TV_IP = _get_tv_ip()


def _load_key() -> str | None:
    try:
        data = json.loads(KEY_FILE.read_text(encoding="utf-8"))
        return data.get("client_key")
    except Exception:
        return None


def _save_key(key: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(json.dumps({"client_key": key, "ip": TV_IP}, indent=2), encoding="utf-8")


def _run_async(coro):
    """Run async coroutine from sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result(timeout=15)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _connect():
    from aiowebostv import WebOsClient

    client = WebOsClient(TV_IP)
    client_key = _load_key()
    await client.connect(client_key=client_key)

    if client.client_key and client.client_key != client_key:
        _save_key(client.client_key)
        print("[LG_TV] Paired! Key saved.")

    return client


async def _send_command(action: str, value: str = "") -> str:
    try:
        client = await _connect()

        if action == "power_off":
            await client.power_off()
            return "TV powered off."

        elif action == "volume_up":
            await client.volume_up()
            return "Volume up."

        elif action == "volume_down":
            await client.volume_down()
            return "Volume down."

        elif action == "volume_set":
            await client.set_volume(int(value))
            return f"Volume set to {value}."

        elif action == "mute":
            await client.set_mute(True)
            return "TV muted."

        elif action == "unmute":
            await client.set_mute(False)
            return "TV unmuted."

        elif action == "channel_up":
            await client.channel_up()
            return "Channel up."

        elif action == "channel_down":
            await client.channel_down()
            return "Channel down."

        elif action == "play":
            await client.play()
            return "Play."

        elif action == "pause":
            await client.pause()
            return "Paused."

        elif action == "stop":
            await client.stop()
            return "Stopped."

        elif action == "input":
            inputs = await client.get_inputs()
            for inp in inputs:
                if value.lower() in inp.get("label", "").lower() or value.lower() in inp.get("id", "").lower():
                    await client.set_input(inp["id"])
                    return f"Switched to {inp.get('label', inp['id'])}."
            available = [f"{i.get('label', '')} ({i['id']})" for i in inputs]
            return f"Input '{value}' not found. Available: {', '.join(available)}"

        elif action == "app":
            apps = await client.get_apps()
            for app in apps:
                if value.lower() in app.get("title", "").lower():
                    await client.launch_app(app["id"])
                    return f"Launched {app['title']}."
            available = [a["title"] for a in apps[:15]]
            return f"App '{value}' not found. Some available: {', '.join(available)}"

        elif action == "info":
            sw = await client.get_software_info()
            vol = await client.get_volume()
            inp = await client.get_current_app()
            return (
                f"LG OLED65E6V at {TV_IP}\n"
                f"WebOS: {sw.get('product_name', '?')} {sw.get('major_ver', '')}.{sw.get('minor_ver', '')}\n"
                f"Volume: {vol.get('volume', '?')} {'(muted)' if vol.get('muted') else ''}\n"
                f"Current app: {inp or 'unknown'}"
            )

        elif action == "screen_off":
            await client.send_command("request", "ssap://com.webos.service.tvpower/power/turnOffScreen")
            return "Screen off (TV still running)."

        elif action == "screen_on":
            await client.send_command("request", "ssap://com.webos.service.tvpower/power/turnOnScreen")
            return "Screen on."

        elif action == "notification":
            await client.send_message(value)
            return f"Notification sent: {value}"

        else:
            return (
                f"Unknown action '{action}'. Use: power_off, volume_up/down/set, mute/unmute, "
                "play/pause/stop, input, app, info, screen_off/on, notification"
            )

    except Exception as e:
        if "rejected" in str(e).lower() or "pair" in str(e).lower():
            return "Pairing required — please accept the prompt on the TV screen, then try again."
        return f"LG TV error: {e}"


def exec_lg_tv(action: str, value: str = "") -> str:
    return _run_async(_send_command(action, value))


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lg_tv",
            "description": "Control the LG webOS TV. Actions: power_off, volume_up, volume_down, volume_set, mute, unmute, play, pause, stop, channel_up, channel_down, input (HDMI1/HDMI2/etc), app (Netflix/YouTube/etc), info, screen_off, screen_on, notification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: power_off, volume_up, volume_down, volume_set, mute, unmute, play, pause, stop, channel_up, channel_down, input, app, info, screen_off, screen_on, notification",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value for action: volume level (0-100), input name (HDMI1), app name (Netflix), or notification text",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {
    "lg_tv": exec_lg_tv,
}

KEYWORDS = {
    "lg_tv": [
        "tv",
        "lg",
        "television",
        "screen",
        "oled",
        "channel",
        "tv volume",
        "tv input",
        "hdmi",
        "screen off",
        "screen on",
        "netflix",
        "youtube",
    ],
}

SKILL_META = {
    "intent_aliases": [
        "lg tv",
        "tv",
        "television",
        "webos",
        "smart tv",
    ],
    "keywords": [
        "lg tv",
        "tv",
        "television",
        "screen",
        "oled",
        "webos",
        "tv volume",
        "tv input",
        "hdmi",
        "screen off",
        "screen on",
        "netflix",
        "youtube",
        "tv app",
    ],
    "route": "reason",
    "tools": {
        "lg_tv": {
            "intent_aliases": [
                "lg tv",
                "tv",
                "television",
                "webos",
                "smart tv",
            ],
            "keywords": [
                "tv",
                "lg",
                "television",
                "screen",
                "oled",
                "channel",
                "tv volume",
                "tv input",
                "hdmi",
                "screen off",
                "screen on",
                "netflix",
                "youtube",
                "pause tv",
                "play tv",
            ],
            "direct_match": [
                "lg tv",
                "tv volume",
                "tv input",
                "screen off",
                "screen on",
                "pause tv",
                "play tv",
            ],
            "route": "reason",
        }
    },
}