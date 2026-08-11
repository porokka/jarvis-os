"""
JARVIS Skill — Flight search via the Duffel API (api.duffel.com).

Replaces Amadeus Self-Service (decommissioned 2026-07-17). Duffel is
self-serve, no IATA/ARC accreditation needed. Search is effectively free
for this use case: charged only past a 1,500-searches-per-confirmed-order
ratio, and JARVIS never books — so real cost stays a few cents/month at
most even polling every few hours.

Env (config in .env):
  DUFFEL_ACCESS_TOKEN — from dashboard.duffel.com (duffel_test_... or
                         duffel_live_... — test tokens return real schedule/
                         price data from a sandbox airline set, not mock data)

Used two ways:
  - ad-hoc: "search flights Helsinki to Bangkok on 2026-10-05"
  - by task_loop's flight_monitor action (see monitor skill)
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional

SKILL_NAME = "flights"
SKILL_DESCRIPTION = (
    "Search real flight prices via the Duffel API. Use for: 'search flights X to Y', "
    "'how much is a flight to Z', 'cheapest flight to X in October'."
)

KEYWORDS = {
    "flight_search": [
        "flight", "flights", "fly", "airfare", "plane ticket", "cheap flight",
        "lento", "lennot",
    ],
}

SKILL_META = {
    "route": "tools",
}

API_BASE = "https://api.duffel.com"
API_VERSION = "v2"


def _token() -> str:
    token = os.environ.get("DUFFEL_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Duffel API key missing — set DUFFEL_ACCESS_TOKEN in .env "
            "(create one free at dashboard.duffel.com)."
        )
    return token


def _post(path: str, body: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps({"data": body}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Duffel-Version": API_VERSION,
            "Authorization": f"Bearer {_token()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Duffel API error {e.code}: {detail}") from e


def _slice_body(origin: str, destination: str, depart_date: str) -> Dict[str, str]:
    return {
        "origin": origin.strip().upper(),
        "destination": destination.strip().upper(),
        "departure_date": depart_date,
    }


def _parse_iso_duration(duration: str) -> str:
    """PT9H35M -> '9h35m'."""
    if not duration:
        return ""
    return duration.replace("PT", "").replace("H", "h").replace("M", "m").lower()


def search_flights(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Return offers sorted by price: [{price, currency, carrier, stops, duration}]."""
    slices = [_slice_body(origin, destination, depart_date)]
    if return_date:
        slices.append(_slice_body(destination, origin, return_date))

    body = {
        "slices": slices,
        "passengers": [{"type": "adult"} for _ in range(max(1, int(adults)))],
        "cabin_class": "economy",
    }

    payload = _post("/air/offer_requests?return_offers=true", body)
    offers = (payload.get("data") or {}).get("offers", [])

    parsed = []
    for offer in offers[:max_results]:
        first_slice = (offer.get("slices") or [{}])[0]
        segments = first_slice.get("segments", [])
        carrier = ""
        if segments:
            carrier = (segments[0].get("operating_carrier") or {}).get("name", "")

        parsed.append({
            "price": float(offer.get("total_amount", 0) or 0),
            "currency": offer.get("total_currency", "EUR"),
            "carrier": carrier or "Unknown",
            "stops": max(0, len(segments) - 1),
            "duration": _parse_iso_duration(first_slice.get("duration", "")),
        })

    parsed.sort(key=lambda o: o["price"])
    return parsed


def cheapest_offer(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    offers = search_flights(origin, destination, depart_date, return_date=return_date, max_results=5)
    return offers[0] if offers else None


def _format_offers(origin: str, destination: str, depart_date: str,
                   return_date: Optional[str], offers: List[Dict[str, Any]]) -> str:
    trip = f"{origin.upper()} → {destination.upper()} {depart_date}"
    if return_date:
        trip += f" (return {return_date})"
    if not offers:
        return f"No flights found for {trip}."
    lines = [f"Flights {trip}:"]
    for o in offers[:5]:
        stops = "direct" if o["stops"] == 0 else f"{o['stops']} stop(s)"
        lines.append(
            f"  {o['price']:.0f} {o['currency']} — {o['carrier']}, {stops}, {o['duration']}"
        )
    return "\n".join(lines)


def exec_flight_search(args: Dict[str, Any] | None = None, **kwargs: Any) -> Dict[str, Any]:
    args = {**(args or {}), **kwargs}
    origin = str(args.get("origin", "")).strip()
    destination = str(args.get("destination", "")).strip()
    depart_date = str(args.get("depart_date", "")).strip()
    return_date = str(args.get("return_date", "")).strip() or None

    if not (origin and destination and depart_date):
        return {
            "ok": False,
            "speech": "I need origin, destination (IATA codes) and a departure date (YYYY-MM-DD).",
            "error": "missing_args",
        }

    try:
        offers = search_flights(origin, destination, depart_date, return_date=return_date)
        text = _format_offers(origin, destination, depart_date, return_date, offers)
        return {"ok": True, "speech": text, "data": {"offers": offers}, "error": None}
    except Exception as e:
        return {"ok": False, "speech": f"Flight search failed: {e}", "error": str(e)}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "flight_search",
            "description": (
                "Search flight prices. Requires IATA airport codes "
                "(Helsinki=HEL, Bangkok=BKK, Tallinn=TLL) and dates as YYYY-MM-DD."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "IATA code, e.g. HEL"},
                    "destination": {"type": "string", "description": "IATA code, e.g. BKK"},
                    "depart_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "return_date": {"type": "string", "description": "YYYY-MM-DD, omit for one-way"},
                },
                "required": ["origin", "destination", "depart_date"],
            },
        },
    },
]

TOOL_MAP = {
    "flight_search": exec_flight_search,
}
