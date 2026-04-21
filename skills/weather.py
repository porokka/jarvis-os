"""
JARVIS Skill — Weather by location.

Uses Open-Meteo geocoding + forecast API.
Provides:
- current weather
- next N day forecast
- optional hourly preview

No API key required.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


SKILL_NAME = "weather"
SKILL_DESCRIPTION = "Weather forecast by location — current weather and next days"
SKILL_VERSION = "1.0.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "utility"
SKILL_TAGS = ["weather", "forecast", "temperature", "rain", "wind", "location"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "weather_forecast",
    "current_weather",
    "daily_forecast",
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
    "network_access": True,
    "entrypoint": "exec_weather",
}
SKILL_META["response_style"] = {
    "default": "human_summary",
    "avoid_raw_dump": True,
    "round_numbers": True,
}
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _truncate(text: str, limit: int = 5000) -> str:
    text = text.replace("**", "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def _http_json(url: str, timeout: int = 12) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _weather_desc(code: Optional[int]) -> str:
    if code is None:
        return "Unknown"
    return WEATHER_CODES.get(code, f"Code {code}")


def _geocode_location(location: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    query = urllib.parse.urlencode({"name": location, "count": 1, "language": "en", "format": "json"})
    url = f"{GEOCODE_URL}?{query}"

    try:
        data = _http_json(url)
        results = data.get("results") or []
        if not results:
            return None, f"No location found for '{location}'."
        return results[0], None
    except Exception as e:
        return None, f"Geocoding error: {e}"


def _build_location_label(place: Dict[str, Any]) -> str:
    parts = []
    name = place.get("name")
    admin1 = place.get("admin1")
    country = place.get("country")

    if name:
        parts.append(str(name))
    if admin1 and str(admin1) != str(name):
        parts.append(str(admin1))
    if country:
        parts.append(str(country))

    return ", ".join(parts) if parts else "Unknown location"


def _fetch_forecast(
    latitude: float,
    longitude: float,
    timezone: str = "auto",
    days: int = 5,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "forecast_days": max(1, min(14, int(days))),
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "is_day",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
        ]),
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
        ]),
        "hourly": ",".join([
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
            "wind_speed_10m",
        ]),
    }

    url = f"{FORECAST_URL}?{urllib.parse.urlencode(params)}"
    try:
        return _http_json(url), None
    except Exception as e:
        return None, f"Forecast error: {e}"


def _format_current(location_label: str, forecast: Dict[str, Any]) -> str:
    current = forecast.get("current") or {}
    time_s = current.get("time", "")
    temp = current.get("temperature_2m")
    app = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    rain = current.get("precipitation")
    wind = current.get("wind_speed_10m")
    code = current.get("weather_code")

    lines = [
        f"Current weather for {location_label}:",
        f"- Condition: {_weather_desc(code)}",
    ]

    if temp is not None:
        lines.append(f"- Temperature: {temp}°C")
    if app is not None:
        lines.append(f"- Feels like: {app}°C")
    if humidity is not None:
        lines.append(f"- Humidity: {humidity}%")
    if rain is not None:
        lines.append(f"- Precipitation: {rain} mm")
    if wind is not None:
        lines.append(f"- Wind: {wind} km/h")
    if time_s:
        lines.append(f"- Updated: {time_s}")

    return "\n".join(lines)


def _format_daily(location_label: str, forecast: Dict[str, Any], days: int) -> str:
    daily = forecast.get("daily") or {}
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    rain = daily.get("precipitation_sum") or []
    pop = daily.get("precipitation_probability_max") or []
    wind = daily.get("wind_speed_10m_max") or []

    lines = [f"{days}-day forecast for {location_label}:"]
    count = min(days, len(times))

    for i in range(count):
        date_label = times[i]
        try:
            dt = datetime.fromisoformat(times[i])
            date_label = dt.strftime("%a %Y-%m-%d")
        except Exception:
            pass

        desc = _weather_desc(codes[i] if i < len(codes) else None)
        hi = tmax[i] if i < len(tmax) else "?"
        lo = tmin[i] if i < len(tmin) else "?"
        r = rain[i] if i < len(rain) else "?"
        p = pop[i] if i < len(pop) else "?"
        w = wind[i] if i < len(wind) else "?"

        lines.append(
            f"- {date_label}: {desc}, {lo}°C to {hi}°C, rain {r} mm, precip {p}%, wind {w} km/h"
        )

    return "\n".join(lines)


def _format_hourly(location_label: str, forecast: Dict[str, Any], hours: int = 12) -> str:
    hourly = forecast.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    pops = hourly.get("precipitation_probability") or []
    codes = hourly.get("weather_code") or []
    winds = hourly.get("wind_speed_10m") or []

    lines = [f"Hourly weather for {location_label} (next {hours}h):"]
    count = min(hours, len(times))

    for i in range(count):
        label = times[i]
        try:
            dt = datetime.fromisoformat(times[i])
            label = dt.strftime("%a %H:%M")
        except Exception:
            pass

        desc = _weather_desc(codes[i] if i < len(codes) else None)
        t = temps[i] if i < len(temps) else "?"
        p = pops[i] if i < len(pops) else "?"
        w = winds[i] if i < len(winds) else "?"

        lines.append(f"- {label}: {desc}, {t}°C, precip {p}%, wind {w} km/h")

    return "\n".join(lines)


def exec_weather(action: str, location: str, days: int = 5) -> str:
    action = (action or "").strip().lower()
    location = (location or "").strip()

    if not location:
        return "Error: location is required."

    if action not in {"current", "forecast", "hourly"}:
        return "Available actions: current, forecast, hourly"

    place, err = _geocode_location(location)
    if err:
        return err
    if not place:
        return f"No location found for '{location}'."

    latitude = place.get("latitude")
    longitude = place.get("longitude")
    if latitude is None or longitude is None:
        return f"Location lookup incomplete for '{location}'."

    forecast, err = _fetch_forecast(float(latitude), float(longitude), days=days)
    if err:
        return err
    if not forecast:
        return "Forecast error: empty response."

    location_label = _build_location_label(place)

    if action == "current":
        return _truncate(_format_current(location_label, forecast), 5000)

    if action == "hourly":
        return _truncate(_format_hourly(location_label, forecast, hours=min(max(days, 1) * 4, 24)), 5000)

    return _truncate(_format_daily(location_label, forecast, days=max(1, min(days, 14))), 5000)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "weather",
            "description": "Get live weather for a location. Actions: current, forecast, hourly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["current", "forecast", "hourly"],
                        "description": "Weather action to perform.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Location name, e.g. Tallinn, Helsinki, London",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days for forecast or hourly preview. Default 5.",
                    },
                },
                "required": ["action", "location"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "weather": exec_weather,
}

KEYWORDS = {
    "weather": [
        "weather",
        "forecast",
        "temperature",
        "rain",
        "snow",
        "wind",
        "weather like",
        "next 5 days",
        "weather in",
    ],
}

SKILL_EXAMPLES = [
    {"command": "weather in Tallinn", "tool": "weather", "args": {"action": "current", "location": "Tallinn"}},
    {"command": "next 5 day forecast for Tallinn", "tool": "weather", "args": {"action": "forecast", "location": "Tallinn", "days": 5}},
    {"command": "hourly weather in Helsinki", "tool": "weather", "args": {"action": "hourly", "location": "Helsinki", "days": 1}},
]