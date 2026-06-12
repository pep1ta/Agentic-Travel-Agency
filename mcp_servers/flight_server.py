# mcp_servers/flight_server.py

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("flight", port=8005)

# ---------------------------------------------------------------------------
# Mock flight data
# ---------------------------------------------------------------------------
#
# These are static mock offers for version 1. The server only provides flight
# options.
#
# Transfers are intentionally not calculated here. A separate mobility server
# will provide transfer information later.
#
# The final policy-based selection happens later in the SmartContractClient,
# not in this MCP server.

FLIGHT_OPTIONS = [
    {
        "offer_id": "flight-1",
        "mode": "flight",
        "provider": "FlightProviderAgent",
        "departure_airport": "DUS",
        "arrival_airport": "MUC",
        "flight_price": 180,
        "flight_duration_minutes": 75,
        "travel_class": "economy",
        "provider_reputation": 88,
        "arrival_buffer_minutes": 60,
    },
    {
        "offer_id": "flight-2",
        "mode": "flight",
        "provider": "FlightProviderAgent",
        "departure_airport": "DUS",
        "arrival_airport": "MUC",
        "flight_price": 220,
        "flight_duration_minutes": 70,
        "travel_class": "business",
        "provider_reputation": 90,
        "arrival_buffer_minutes": 80,
    },
]


@mcp.tool()
def search_flight_options(origin: str, destination: str, appointment_time: str) -> list[dict]:
    """Returns mock flight options for a business travel request.

    Args:
        origin: Start city or region from the user request.
        destination: Destination city or region from the user request.
        appointment_time: Appointment time the traveler needs to arrive for.
    """
    # Version 1 keeps this deliberately simple: the input parameters are part
    # of the tool interface, but the mock server always returns the same offers.
    return FLIGHT_OPTIONS.copy()


if __name__ == "__main__":
    mcp.run(transport="sse")
