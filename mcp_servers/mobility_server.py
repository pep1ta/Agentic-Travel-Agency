# mcp_servers/mobility_server.py

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mobility", port=8006)

# ---------------------------------------------------------------------------
# Mock transfer data
# ---------------------------------------------------------------------------
#
# These are static mock transfer details for version 1. The server only
# provides transfer information.
#
# The later BusinessTravelAgent will combine flight offers with these transfer
# details.
#
# The final policy-based selection happens later in the SmartContractClient,
# not in this MCP server.

AIRPORT_TRANSFERS = {
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


@mcp.tool()
def get_airport_transfers(
    origin: str,
    destination: str,
    departure_airport: str,
    arrival_airport: str,
) -> dict:
    """Returns mock airport transfer information for a flight option.

    Args:
        origin: Start city or station from the user request.
        destination: Destination city or station from the user request.
        departure_airport: Airport code or name where the flight starts.
        arrival_airport: Airport code or name where the flight arrives.
    """
    # Version 1 keeps this deliberately simple: the input parameters are part
    # of the tool interface, but the mock server always returns the same data.
    return AIRPORT_TRANSFERS.copy()


if __name__ == "__main__":
    mcp.run(transport="sse")
