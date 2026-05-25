# mcp_servers/hotel_server.py

from datetime import datetime
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hotel", port=8003)

# ---------------------------------------------------------------------------
# Mock hotel data — same 3 hotels for every city
# ---------------------------------------------------------------------------

HOTELS = [
    {"name": "Budget Inn",   "category": "budget",  "price_per_night": 60},
    {"name": "City Hotel",   "category": "mid",     "price_per_night": 120},
    {"name": "Grand Palace", "category": "luxury",  "price_per_night": 280},
]


def _calculate_nights(checkin: str, checkout: str) -> int:
    """Calculates the number of nights between checkin and checkout (format: YYYY-MM-DD)."""
    fmt = "%Y-%m-%d"
    return (datetime.strptime(checkout, fmt) - datetime.strptime(checkin, fmt)).days


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_hotels(city: str) -> str:
    """Returns available hotels for a given city.

    Args:
        city: The city to search hotels in.
    """
    lines = [f"Available hotels in {city}:"]
    for h in HOTELS:
        lines.append(f"- {h['name']} ({h['category']}) — ${h['price_per_night']}/night")
    return "\n".join(lines)


@mcp.tool()
def book_hotel(hotel_name: str, city: str, checkin: str, checkout: str) -> str:
    """Books a hotel and returns a booking confirmation and invoice.

    Args:
        hotel_name: Name of the hotel to book.
        city: The city where the hotel is located.
        checkin: Check-in date in YYYY-MM-DD format.
        checkout: Check-out date in YYYY-MM-DD format.
    """
    hotel = next((h for h in HOTELS if h["name"].lower() == hotel_name.lower()), None)
    if not hotel:
        return f"Hotel '{hotel_name}' not found. Available: {[h['name'] for h in HOTELS]}"

    try:
        nights = _calculate_nights(checkin, checkout)
    except ValueError:
        return "Invalid date format. Please use YYYY-MM-DD."

    if nights <= 0:
        return "Checkout date must be after checkin date."

    total = hotel["price_per_night"] * nights

    confirmation = (
        f"Booking Confirmation\n"
        f"====================\n"
        f"Hotel:    {hotel['name']} ({hotel['category']})\n"
        f"City:     {city}\n"
        f"Check-in: {checkin}\n"
        f"Check-out:{checkout}\n"
        f"Nights:   {nights}\n"
        f"\n"
        f"Invoice\n"
        f"=======\n"
        f"${hotel['price_per_night']}/night x {nights} nights = ${total}\n"
        f"Total due: ${total}"
    )
    return confirmation


if __name__ == "__main__":
    mcp.run(transport="sse")