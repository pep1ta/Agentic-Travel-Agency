# Run with: uv run python test/providers/verify_provider_agents.py

"""Smoke tests for RailProviderAgent, FlightProviderAgent, MobilityProviderAgent.

Tests invoke() in-process with stubbed MCP calls. No running MCP server or
A2A server is required. This verifies that each provider agent:
  - parses JSON input correctly
  - delegates to the right MCP tool
  - returns valid JSON in the expected format
  - handles invalid input gracefully
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agents.flight.agent as _flight_module
import agents.mobility.agent as _mobility_module
import agents.rail.agent as _rail_module
from agents.flight.agent import FlightProviderAgent
from agents.mobility.agent import MobilityProviderAgent
from agents.rail.agent import RailProviderAgent


# ---------------------------------------------------------------------------
# Stub helper — patches call_mcp_tool in the agent's module
# ---------------------------------------------------------------------------

_AGENT_MODULES = {
    RailProviderAgent: (_rail_module, "RAIL_MCP_URL"),
    FlightProviderAgent: (_flight_module, "FLIGHT_MCP_URL"),
    MobilityProviderAgent: (_mobility_module, "MOBILITY_MCP_URL"),
}


def _stub_mcp(agent: Any, tool_results: dict[str, Any]) -> None:
    """Patches call_mcp_tool in the agent's module with a stub returning predefined data.

    Also sets the required MCP URL env var to a dummy value so the URL check passes.
    """
    module, url_env_var = _AGENT_MODULES[type(agent)]

    async def fake_call_mcp_tool(url: str, tool_name: str, args: dict) -> Any:
        if tool_name not in tool_results:
            raise ValueError(f"Stub has no result for tool '{tool_name}'")
        return tool_results[tool_name]

    module.call_mcp_tool = fake_call_mcp_tool
    os.environ.setdefault(url_env_var, "http://stub-mcp/sse")


# ---------------------------------------------------------------------------
# Stub data — mirrors the static mock data in mcp_servers/
# ---------------------------------------------------------------------------

_RAIL_OFFERS_DORTMUND_MUNICH = [
    {
        "offer_id": "rail-1",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "InterCity Railways",
        "origin": "Dortmund Hbf",
        "destination": "München Hbf",
        "total_price": 119,
        "duration_minutes": 395,
        "travel_class": "second_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 75,
        "transfers_included": True,
        "changes": 1,
        "source": "mock",
    },
    {
        "offer_id": "rail-2",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "FlexTrack Rail",
        "origin": "Dortmund Hbf",
        "destination": "München Hbf",
        "total_price": 89,
        "duration_minutes": 560,
        "travel_class": "second_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 45,
        "transfers_included": True,
        "changes": 3,
        "source": "mock",
    },
]

_RAIL_BOOKING_RESULT = {
    "providerBookingReference": "RAIL-SIM-RAIL-1",
    "offerId": "rail-1",
    "provider": "RailProviderAgent",
    "status": "simulated_confirmed",
    "message": "Simulated rail booking confirmation. No real booking was performed.",
}

_FLIGHT_OFFERS_DORTMUND_VIENNA = [
    {
        "offer_id": "flight-1",
        "mode": "flight",
        "provider": "FlightProviderAgent",
        "carrier": "EuroSky Airlines",
        "departure_airport": "DUS",
        "arrival_airport": "VIE",
        "flight_price": 210,
        "flight_duration_minutes": 95,
        "travel_class": "economy",
        "provider_reputation": 88,
        "arrival_buffer_minutes": 70,
    },
    {
        "offer_id": "flight-2",
        "mode": "flight",
        "provider": "FlightProviderAgent",
        "carrier": "BudgetJet Air",
        "departure_airport": "DUS",
        "arrival_airport": "VIE",
        "flight_price": 260,
        "flight_duration_minutes": 90,
        "travel_class": "economy",
        "provider_reputation": 90,
        "arrival_buffer_minutes": 80,
    },
]

_FLIGHT_BOOKING_RESULT = {
    "providerBookingReference": "FLIGHT-SIM-FLIGHT-1",
    "offerId": "flight-1",
    "provider": "FlightProviderAgent",
    "status": "simulated_confirmed",
    "message": "Simulated flight booking confirmation. No real booking was performed.",
}

_TRANSFER_DATA_MUNICH = {
    "transfers_available": True,
    "origin_to_airport": {
        "from": "Dortmund",
        "to": "Düsseldorf Airport",
        "duration_minutes": 65,
        "price": 22,
    },
    "airport_to_destination": {
        "from": "München Airport",
        "to": "München Hbf",
        "duration_minutes": 45,
        "price": 14,
    },
    "total_transfer_duration_minutes": 110,
    "total_transfer_price": 36,
}

_TRANSFER_DATA_VIENNA = {
    "transfers_available": True,
    "origin_to_airport": {
        "from": "Dortmund",
        "to": "Düsseldorf Airport",
        "duration_minutes": 65,
        "price": 22,
    },
    "airport_to_destination": {
        "from": "Vienna Airport",
        "to": "Wien Hbf",
        "duration_minutes": 25,
        "price": 18,
    },
    "total_transfer_duration_minutes": 90,
    "total_transfer_price": 40,
}


# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------

def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


# ---------------------------------------------------------------------------
# RailProviderAgent tests
# ---------------------------------------------------------------------------

async def _verify_rail_search(failures: list[str]) -> None:
    agent = RailProviderAgent()
    _stub_mcp(agent, {"search_rail_options": _RAIL_OFFERS_DORTMUND_MUNICH})

    request = json.dumps({
        "origin": "Dortmund",
        "destination": "Muenchen",
        "appointment_time": "Montag um 10 uhr",
    })
    response, input_required = await agent.invoke(request)

    _require(not input_required, "RailProviderAgent search: should not require input.", failures)

    try:
        offers = json.loads(response)
    except json.JSONDecodeError:
        failures.append(f"RailProviderAgent search: response is not valid JSON: {response[:200]}")
        return

    _require(isinstance(offers, list), "RailProviderAgent search: should return a list.", failures)
    _require(len(offers) == 2, f"RailProviderAgent search: expected 2 offers, got {len(offers)}.", failures)
    _require(
        offers[0].get("offer_id") == "rail-1",
        f"RailProviderAgent search: first offer_id should be 'rail-1', got {offers[0].get('offer_id')}.",
        failures,
    )
    _require(
        all(o.get("mode") == "rail" for o in offers),
        "RailProviderAgent search: all offers should have mode='rail'.",
        failures,
    )


async def _verify_rail_booking(failures: list[str]) -> None:
    agent = RailProviderAgent()
    _stub_mcp(agent, {"book_rail_offer": _RAIL_BOOKING_RESULT})

    request = json.dumps({"action": "book", "offer_id": "rail-1"})
    response, input_required = await agent.invoke(request)

    _require(not input_required, "RailProviderAgent book: should not require input.", failures)

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        failures.append(f"RailProviderAgent book: response is not valid JSON: {response[:200]}")
        return

    _require(
        result.get("status") == "simulated_confirmed",
        f"RailProviderAgent book: expected simulated_confirmed, got {result.get('status')}.",
        failures,
    )
    _require(
        result.get("offerId") == "rail-1",
        f"RailProviderAgent book: expected offerId 'rail-1', got {result.get('offerId')}.",
        failures,
    )


# ---------------------------------------------------------------------------
# FlightProviderAgent tests
# ---------------------------------------------------------------------------

async def _verify_flight_search(failures: list[str]) -> None:
    agent = FlightProviderAgent()
    _stub_mcp(agent, {"search_flight_options": _FLIGHT_OFFERS_DORTMUND_VIENNA})

    request = json.dumps({
        "origin": "Dortmund",
        "destination": "Wien",
        "appointment_time": "Montag um 10 uhr",
    })
    response, input_required = await agent.invoke(request)

    _require(not input_required, "FlightProviderAgent search: should not require input.", failures)

    try:
        offers = json.loads(response)
    except json.JSONDecodeError:
        failures.append(f"FlightProviderAgent search: response is not valid JSON: {response[:200]}")
        return

    _require(isinstance(offers, list), "FlightProviderAgent search: should return a list.", failures)
    _require(len(offers) == 2, f"FlightProviderAgent search: expected 2 offers, got {len(offers)}.", failures)
    _require(
        offers[0].get("offer_id") == "flight-1",
        f"FlightProviderAgent search: first offer_id should be 'flight-1', got {offers[0].get('offer_id')}.",
        failures,
    )
    _require(
        all(o.get("mode") == "flight" for o in offers),
        "FlightProviderAgent search: all offers should have mode='flight' (not flight_with_transfers).",
        failures,
    )
    _require(
        offers[0].get("departure_airport") == "DUS",
        "FlightProviderAgent search: departure_airport should be 'DUS'.",
        failures,
    )


async def _verify_flight_booking(failures: list[str]) -> None:
    agent = FlightProviderAgent()
    _stub_mcp(agent, {"book_flight_offer": _FLIGHT_BOOKING_RESULT})

    request = json.dumps({"action": "book", "offer_id": "flight-1"})
    response, input_required = await agent.invoke(request)

    _require(not input_required, "FlightProviderAgent book: should not require input.", failures)

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        failures.append(f"FlightProviderAgent book: response is not valid JSON: {response[:200]}")
        return

    _require(
        result.get("status") == "simulated_confirmed",
        f"FlightProviderAgent book: expected simulated_confirmed, got {result.get('status')}.",
        failures,
    )


# ---------------------------------------------------------------------------
# MobilityProviderAgent tests
# ---------------------------------------------------------------------------

async def _verify_mobility_munich(failures: list[str]) -> None:
    agent = MobilityProviderAgent()
    _stub_mcp(agent, {"get_airport_transfers": _TRANSFER_DATA_MUNICH})

    request = json.dumps({
        "origin": "Dortmund",
        "destination": "Muenchen",
        "departure_airport": "DUS",
        "arrival_airport": "MUC",
    })
    response, input_required = await agent.invoke(request)

    _require(not input_required, "MobilityProviderAgent MUC: should not require input.", failures)

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        failures.append(f"MobilityProviderAgent MUC: response is not valid JSON: {response[:200]}")
        return

    _require(
        result.get("transfers_available") is True,
        "MobilityProviderAgent MUC: transfers_available should be True.",
        failures,
    )
    _require(
        result.get("total_transfer_price") == 36,
        f"MobilityProviderAgent MUC: expected total_transfer_price 36, got {result.get('total_transfer_price')}.",
        failures,
    )
    _require(
        result.get("total_transfer_duration_minutes") == 110,
        f"MobilityProviderAgent MUC: expected duration 110, got {result.get('total_transfer_duration_minutes')}.",
        failures,
    )


async def _verify_mobility_vienna(failures: list[str]) -> None:
    agent = MobilityProviderAgent()
    _stub_mcp(agent, {"get_airport_transfers": _TRANSFER_DATA_VIENNA})

    request = json.dumps({
        "origin": "Dortmund",
        "destination": "Wien",
        "departure_airport": "DUS",
        "arrival_airport": "VIE",
    })
    response, input_required = await agent.invoke(request)

    _require(not input_required, "MobilityProviderAgent VIE: should not require input.", failures)

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        failures.append(f"MobilityProviderAgent VIE: response is not valid JSON: {response[:200]}")
        return

    _require(
        result.get("total_transfer_price") == 40,
        f"MobilityProviderAgent VIE: expected total_transfer_price 40, got {result.get('total_transfer_price')}.",
        failures,
    )


# ---------------------------------------------------------------------------
# Error handling test
# ---------------------------------------------------------------------------

async def _verify_invalid_json_handling(failures: list[str]) -> None:
    """All provider agents return an error dict for non-JSON input."""
    agents = [
        ("RailProviderAgent", RailProviderAgent()),
        ("FlightProviderAgent", FlightProviderAgent()),
        ("MobilityProviderAgent", MobilityProviderAgent()),
    ]

    for name, agent in agents:
        response, input_required = await agent.invoke("this is not json")
        _require(
            not input_required,
            f"{name} invalid input: should not require input.",
            failures,
        )
        try:
            result = json.loads(response)
            _require(
                "error" in result,
                f"{name} invalid input: response should contain 'error' key.",
                failures,
            )
        except json.JSONDecodeError:
            failures.append(f"{name} invalid input: response is not valid JSON: {response[:200]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    failures: list[str] = []

    await _verify_rail_search(failures)
    await _verify_rail_booking(failures)
    await _verify_flight_search(failures)
    await _verify_flight_booking(failures)
    await _verify_mobility_munich(failures)
    await _verify_mobility_vienna(failures)
    await _verify_invalid_json_handling(failures)

    if failures:
        print("Provider agent verification failed.")
        for failure in failures:
            print(f"- {failure}")
        raise AssertionError(f"{len(failures)} provider agent verification checks failed.")

    print("RailProviderAgent: search returns 2 rail offers (Dortmund -> Muenchen).")
    print("RailProviderAgent: booking returns simulated_confirmed.")
    print("FlightProviderAgent: search returns 2 flight offers (Dortmund -> Wien).")
    print("FlightProviderAgent: booking returns simulated_confirmed.")
    print("MobilityProviderAgent: Munich transfers - price=36, duration=110 min.")
    print("MobilityProviderAgent: Vienna transfers - price=40, duration=90 min.")
    print("All provider agents: invalid JSON input returns error dict.")
    print("Provider agent verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
