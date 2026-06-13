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

FLIGHT_OPTIONS_DORTMUND_MUNICH = [
    {
        "offer_id": "flight-1",
        "mode": "flight",
        "provider": "FlightProviderAgent",
        "carrier": "EuroSky Airlines",
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
        "carrier": "BudgetJet Air",
        "departure_airport": "DUS",
        "arrival_airport": "MUC",
        "flight_price": 220,
        "flight_duration_minutes": 70,
        "travel_class": "business",
        "provider_reputation": 90,
        "arrival_buffer_minutes": 80,
    },
]

FLIGHT_OPTIONS_DORTMUND_VIENNA = [
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

KNOWN_FLIGHT_OFFER_IDS = {
    offer["offer_id"]
    for options in [
        FLIGHT_OPTIONS_DORTMUND_MUNICH,
        FLIGHT_OPTIONS_DORTMUND_VIENNA,
    ]
    for offer in options
}
KNOWN_FLIGHT_OFFER_IDS.update(
    f"{offer_id}-with-transfers" for offer_id in list(KNOWN_FLIGHT_OFFER_IDS)
)


@mcp.tool()
def search_flight_options(origin: str, destination: str, appointment_time: str) -> list[dict]:
    """Returns mock flight options for a business travel request.

    Args:
        origin: Start city or region from the user request.
        destination: Destination city or region from the user request.
        appointment_time: Appointment time the traveler needs to arrive for.
    """
    # Version 1 keeps this deliberately simple: the input parameters are part
    # of the tool interface, and the mock server switches only between the
    # two didactic demo routes.
    origin_lower = origin.lower()
    destination_lower = destination.lower()

    if "dortmund" in origin_lower and ("wien" in destination_lower or "vienna" in destination_lower):
        return FLIGHT_OPTIONS_DORTMUND_VIENNA.copy()

    return FLIGHT_OPTIONS_DORTMUND_MUNICH.copy()


@mcp.tool()
def book_flight_offer(offer_id: str) -> dict:
    """Simulates a flight provider booking confirmation.

    This is mock provider behavior only. No real flight is booked and no
    provider payment is executed here.
    """
    if offer_id not in KNOWN_FLIGHT_OFFER_IDS:
        return {
            "offerId": offer_id,
            "provider": "FlightProviderAgent",
            "status": "error",
            "message": f"Unknown flight offer_id: {offer_id}",
        }

    return {
        "providerBookingReference": f"FLIGHT-SIM-{offer_id.upper()}",
        "offerId": offer_id,
        "provider": "FlightProviderAgent",
        "status": "simulated_confirmed",
        "message": "Simulated flight booking confirmation. No real booking was performed.",
    }


if __name__ == "__main__":
    mcp.run(transport="sse")
