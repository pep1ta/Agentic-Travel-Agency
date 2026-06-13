"""Optional rail API adapter with safe mock fallback behavior.

The Business Travel demo normally uses static mock offers. If USE_RAIL_API=true
is set, this adapter tries to read journeys from https://v6.db.transport.rest
and normalizes them into the same simple offer dictionaries used by the policy
mock.

Any error returns an empty list so the MCP server can fall back to mocks.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://v6.db.transport.rest"
SIMULATED_OPERATORS = ["InterCity Railways", "FlexTrack Rail"]


def rail_api_enabled() -> bool:
    """Returns whether the external rail API should be tried."""
    return os.environ.get("USE_RAIL_API", "").lower() == "true"


def search_rail_api_options(
    origin: str,
    destination: str,
    appointment_time: str,
) -> list[dict]:
    """Return normalized rail offers from the optional journey API.

    The function is intentionally defensive. If lookup, journey search, or
    normalization fails, it returns [] and lets the caller use mock fallback
    data.
    """
    if not rail_api_enabled():
        return []

    base_url = os.environ.get("RAIL_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

    try:
        with httpx.Client(timeout=8.0) as client:
            origin_id = _lookup_station_id(client, base_url, origin)
            destination_id = _lookup_station_id(client, base_url, destination)

            if not origin_id or not destination_id:
                return []

            response = client.get(
                f"{base_url}/journeys",
                params={
                    "from": origin_id,
                    "to": destination_id,
                    "results": 3,
                },
            )
            response.raise_for_status()
            data = response.json()
            journeys = data.get("journeys", [])

            offers = []
            for index, journey in enumerate(journeys[:3], start=1):
                offer = _normalize_journey(
                    journey,
                    index,
                    origin,
                    destination,
                    appointment_time,
                )
                if offer:
                    offers.append(offer)

            return offers

    except Exception:
        return []


def _lookup_station_id(client: httpx.Client, base_url: str, query: str) -> str | None:
    """Find the first station/location id for a query."""
    response = client.get(
        f"{base_url}/locations",
        params={
            "query": query,
            "results": 1,
        },
    )
    response.raise_for_status()
    locations = response.json()

    if not locations:
        return None

    return locations[0].get("id")


def _normalize_journey(
    journey: dict[str, Any],
    index: int,
    origin: str,
    destination: str,
    appointment_time: str,
) -> dict | None:
    """Convert one journey API response to a policy-compatible rail offer."""
    legs = journey.get("legs", [])

    if not legs:
        return None

    departure_time = _parse_time(
        legs[0].get("plannedDeparture")
        or legs[0].get("prognosedDeparture")
        or legs[0].get("departure")
    )
    arrival_time = _parse_time(
        legs[-1].get("plannedArrival")
        or legs[-1].get("prognosedArrival")
        or legs[-1].get("arrival")
    )

    if not departure_time or not arrival_time:
        return None

    duration_minutes = max(1, int((arrival_time - departure_time).total_seconds() // 60))
    changes = max(0, len(legs) - 1)
    arrival_buffer_minutes = _arrival_buffer_minutes(appointment_time, arrival_time)

    return {
        "offer_id": f"api-rail-{index}",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": SIMULATED_OPERATORS[(index - 1) % len(SIMULATED_OPERATORS)],
        "origin": origin,
        "destination": destination,
        "total_price": _estimate_price(duration_minutes, changes),
        "price_estimated": True,
        "duration_minutes": duration_minutes,
        "travel_class": "second_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": arrival_buffer_minutes,
        "transfers_included": True,
        "changes": changes,
        "source": "api",
    }


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _arrival_buffer_minutes(appointment_time: str, arrival_time: datetime) -> int:
    """Best-effort arrival buffer.

    Demo requests often use simple text such as "Monday 10:00". If no concrete
    ISO timestamp is available, keep a stable policy-friendly default.
    """
    appointment = _parse_time(appointment_time)

    if not appointment:
        return 60

    return max(0, int((appointment - arrival_time).total_seconds() // 60))


def _estimate_price(duration_minutes: int, changes: int) -> int:
    """Simple deterministic prototype price estimate."""
    return max(49, int(duration_minutes * 0.22) + changes * 12)
