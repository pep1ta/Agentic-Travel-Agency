# mcp_servers/rail_server.py

import unicodedata

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("rail", port=8004)

# ---------------------------------------------------------------------------
# Mock rail data
# ---------------------------------------------------------------------------
#
# These are static mock offers for version 1. The server only provides travel
# information. It does not decide which offer is best.
#
# The final policy-based selection happens later in the SmartContractClient,
# not in this MCP server.

RAIL_OPTIONS_DORTMUND_MUNICH = [
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
    },
    {
        "offer_id": "rail-3",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "InterCity Railways",
        "origin": "Dortmund Hbf",
        "destination": "München Hbf",
        "total_price": 150,
        "duration_minutes": 390,
        "travel_class": "first_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 90,
        "transfers_included": True,
        "changes": 0,
    },
]

RAIL_OPTIONS_DORTMUND_VIENNA = [
    {
        "offer_id": "rail-vienna-1",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "InterCity Railways",
        "origin": "Dortmund Hbf",
        "destination": "Wien Hbf",
        "total_price": 139,
        "duration_minutes": 620,
        "travel_class": "second_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 60,
        "transfers_included": True,
        "changes": 2,
    },
    {
        "offer_id": "rail-vienna-2",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "FlexTrack Rail",
        "origin": "Dortmund Hbf",
        "destination": "Wien Hbf",
        "total_price": 109,
        "duration_minutes": 710,
        "travel_class": "second_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 45,
        "transfers_included": True,
        "changes": 3,
    },
    {
        "offer_id": "rail-vienna-3",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "InterCity Railways",
        "origin": "Dortmund Hbf",
        "destination": "Wien Hbf",
        "total_price": 180,
        "duration_minutes": 470,
        "travel_class": "first_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 90,
        "transfers_included": True,
        "changes": 1,
    },
]

RAIL_OPTIONS_MUNSTER_MUNICH = [
    {
        "offer_id": "rail-muenster-1",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "InterCity Railways",
        "origin": "Münster Hbf",
        "destination": "München Hbf",
        "total_price": 129,
        "duration_minutes": 430,
        "travel_class": "second_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 70,
        "transfers_included": True,
        "changes": 1,
    },
    {
        "offer_id": "rail-muenster-2",
        "mode": "rail",
        "provider": "RailProviderAgent",
        "operator": "FlexTrack Rail",
        "origin": "Münster Hbf",
        "destination": "München Hbf",
        "total_price": 99,
        "duration_minutes": 590,
        "travel_class": "second_class",
        "provider_reputation": 82,
        "arrival_buffer_minutes": 45,
        "transfers_included": True,
        "changes": 3,
    },
]

KNOWN_RAIL_OFFER_IDS = {
    offer["offer_id"]
    for options in [
        RAIL_OPTIONS_DORTMUND_MUNICH,
        RAIL_OPTIONS_DORTMUND_VIENNA,
        RAIL_OPTIONS_MUNSTER_MUNICH,
    ]
    for offer in options
}


def _with_mock_source(options: list[dict]) -> list[dict]:
    """Returns shallow copies marked as mock offers."""
    return [{**offer, "source": "mock"} for offer in options]


def _normalize(text: str) -> str:
    """Normalizes German umlauts enough for simple mock route matching."""
    text = text.lower().replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


@mcp.tool()
def search_rail_options(origin: str, destination: str, appointment_time: str) -> list[dict]:
    """Returns rail options for a business travel request.

    Args:
        origin: Start station or city from the user request.
        destination: Destination station or city from the user request.
        appointment_time: Appointment time the traveler needs to arrive for.
    """
    # Version 1 keeps this deliberately simple: the input parameters are part
    # of the tool interface, and the mock server switches only between the
    # didactic demo routes.
    origin_normalized = _normalize(origin)
    destination_normalized = _normalize(destination)

    if "dortmund" in origin_normalized and "muenchen" in destination_normalized:
        return _with_mock_source(RAIL_OPTIONS_DORTMUND_MUNICH)

    if "dortmund" in origin_normalized and ("wien" in destination_normalized or "vienna" in destination_normalized):
        return _with_mock_source(RAIL_OPTIONS_DORTMUND_VIENNA)

    if "muenster" in origin_normalized and "muenchen" in destination_normalized:
        return _with_mock_source(RAIL_OPTIONS_MUNSTER_MUNICH)

    return []


@mcp.tool()
def book_rail_offer(offer_id: str) -> dict:
    """Simulates a rail provider booking confirmation.

    This is mock provider behavior only. No real ticket is booked and no
    provider payment is executed here.
    """
    if offer_id not in KNOWN_RAIL_OFFER_IDS:
        return {
            "offerId": offer_id,
            "provider": "RailProviderAgent",
            "status": "error",
            "message": f"Unknown rail offer_id: {offer_id}",
        }

    return {
        "providerBookingReference": f"RAIL-SIM-{offer_id.upper()}",
        "offerId": offer_id,
        "provider": "RailProviderAgent",
        "status": "simulated_confirmed",
        "message": "Simulated rail booking confirmation. No real booking was performed.",
    }


if __name__ == "__main__":
    mcp.run(transport="sse")
