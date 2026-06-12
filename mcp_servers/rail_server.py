# mcp_servers/rail_server.py

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


@mcp.tool()
def search_rail_options(origin: str, destination: str, appointment_time: str) -> list[dict]:
    """Returns mock rail options for a business travel request.

    Args:
        origin: Start station or city from the user request.
        destination: Destination station or city from the user request.
        appointment_time: Appointment time the traveler needs to arrive for.
    """
    # Version 1 keeps this deliberately simple: the input parameters are part
    # of the tool interface, and the mock server switches only between the
    # two didactic demo routes.
    origin_lower = origin.lower()
    destination_lower = destination.lower()

    if "dortmund" in origin_lower and ("münchen" in destination_lower or "muenchen" in destination_lower):
        return RAIL_OPTIONS_DORTMUND_MUNICH.copy()

    if "dortmund" in origin_lower and ("wien" in destination_lower or "vienna" in destination_lower):
        return RAIL_OPTIONS_DORTMUND_VIENNA.copy()

    return []


if __name__ == "__main__":
    mcp.run(transport="sse")
