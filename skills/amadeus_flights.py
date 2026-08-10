"""
JARVIS Skill — Flight search via the Amadeus Self-Service API.

Env (config in .env):
  AMADEUS_CLIENT_ID      — from developers.amadeus.com
  AMADEUS_CLIENT_SECRET
  AMADEUS_ENV            — "test" (default, free tier) or "prod"

Used two ways:
  - ad-hoc: "search flights Helsinki to Bangkok on 2026-10-05"
  - by task_loop's flight_monitor action (see monitor skill)
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

SKILL_NAME = "flights"
SKILL_DESCRIPTION = (
    "Search real flight prices via the Amadeus API. Use for: 'search flights X to Y', "
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

_TOKEN: Dict[str, Any] = {"value": None, "expires_at": 0.0}


def _base_url() -> str:
    env = os.environ.get("AMADEUS_ENV", "test").strip().lower()
    return "https://api.amadeus.com" if env == "prod" else "https://test.api.amadeus.com"


def _get_token() -> str:
    if _TOKEN["value"] and time.time() < _TOKEN["expires_at"] - 60:
        return _TOKEN["value"]

    client_id = os.environ.get("AMADEUS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AMADEUS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Amadeus API keys missing — set AMADEUS_CLIENT_ID and "
            "AMADEUS_CLIENT_SECRET in .env (register free at developers.amadeus.com)."
        )

    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(
        f"{_base_url()}/v1/security/oauth2/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    _TOKEN["value"] = payload["access_token"]
    _TOKEN["expires_at"] = time.time() + int(payload.get("expires_in", 1799))
    return _TOKEN["value"]


def search_flights(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    currency: str = "EUR",
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Return offers sorted by price: [{price, currency, carrier, stops, duration}]."""
    params = {
        "originLocationCode": origin.strip().upper(),
        "destinationLocationCode": destination.strip().upper(),
        "departureDate": depart_date,
        "adults": str(max(1, int(adults))),
        "currencyCode": currency,
        "max": str(max(1, min(int(max_results), 20))),
    }
    if return_date:
        params["returnDate"] = return_date

    req = urllib.request.Request(
        f"{_base_url()}/v2/shopping/flight-offers?" + urllib.parse.urlencode(params),
        headers={"Authorization": f"Bearer {_get_token()}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    carriers = (payload.get("dictionaries") or {}).get("carriers", {})
    offers = []
    for offer in payload.get("data", []):
        price = float(offer.get("price", {}).get("grandTotal", 0))
        itineraries = offer.get("itineraries", [])
        first = itineraries[0] if itineraries else {}
        segments = first.get("segments", [])
        carrier_code = segments[0].get("carrierCode", "") if segments else ""
        offers.append({
            "price": price,
            "currency": currency,
            "carrier": carriers.get(carrier_code, carrier_code),
            "stops": max(0, len(segments) - 1),
            "duration": first.get("duration", "").replace("PT", "").lower(),
        })

    offers.sort(key=lambda o: o["price"])
    return offers


def cheapest_offer(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: Optional[str] = None,
    currency: str = "EUR",
) -> Optional[Dict[str, Any]]:
    offers = search_flights(
        origin, destination, depart_date,
        return_date=return_date, currency=currency, max_results=5,
    )
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
