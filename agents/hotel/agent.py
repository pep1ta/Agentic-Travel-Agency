# agents/hotel/agent.py

import logging
from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)

MCP_URL = "http://localhost:8003/sse"


class BookingState:
    """Tracks the multi-turn booking conversation state."""

    def __init__(self):
        self.city: str | None = None
        self.hotel_name: str | None = None
        self.checkin: str | None = None
        self.checkout: str | None = None
        self.awaiting_confirmation: bool = False


class HotelAgent:
    """Hotel booking agent.

    Handles multi-turn conversations for hotel search and booking.
    Uses an MCP server for hotel data — search and booking logic lives there.
    State is maintained per context_id so parallel conversations don't interfere.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        # context_id → BookingState — tracks state per conversation
        self._sessions: dict[str, BookingState] = {}

    def _get_state(self, context_id: str) -> BookingState:
        """Returns existing state for a context or creates a new one."""
        if context_id not in self._sessions:
            self._sessions[context_id] = BookingState()
        return self._sessions[context_id]

    # -----------------------------------------------------------------------
    # MCP calls
    # -----------------------------------------------------------------------

    async def _search_hotels(self, city: str) -> str:
        """Calls the hotel MCP server to search for hotels in a city."""
        async with sse_client(MCP_URL) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool("search_hotels", {"city": city})
                return result.content[0].text if result.content else "(no results)"

    async def _book_hotel(self, hotel_name: str, city: str, checkin: str, checkout: str) -> str:
        """Calls the hotel MCP server to book a hotel."""
        async with sse_client(MCP_URL) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool("book_hotel", {
                    "hotel_name": hotel_name,
                    "city": city,
                    "checkin": checkin,
                    "checkout": checkout,
                })
                return result.content[0].text if result.content else "(no result)"

    # -----------------------------------------------------------------------
    # Multi-turn invoke
    # -----------------------------------------------------------------------

    async def invoke(self, query: str, context_id: str) -> tuple[str, bool]:
        """Processes a user message and returns (response, input_required).

        Returns input_required=True when the agent needs more information
        or is waiting for the user to confirm a booking.
        """
        state = self._get_state(context_id)
        query_lower = query.lower().strip()

        # --- Step 4: User confirmed booking ---
        if state.awaiting_confirmation:
            if any(word in query_lower for word in ["yes", "ja", "confirm", "book", "bestätige", "buchen"]):
                state.awaiting_confirmation = False
                result = await self._book_hotel(
                    state.hotel_name, state.city, state.checkin, state.checkout
                )
                # Clear state after successful booking
                del self._sessions[context_id]
                return result, False
            else:
                del self._sessions[context_id]
                return "Booking cancelled. Let me know if you need anything else.", False

        # --- Extract info from query ---
        self._parse_query(query, state)

        # --- Step 1: Need city ---
        if not state.city:
            return "Which city would you like to book a hotel in?", True

        # --- Step 2: Show hotels if no hotel selected yet ---
        if not state.hotel_name:
            hotels = await self._search_hotels(state.city)
            return (
                f"{hotels}\n\n"
                f"Which hotel would you like to book? (Budget Inn / City Hotel / Grand Palace)",
                True
            )

        # --- Step 3: Need checkin/checkout ---
        if not state.checkin:
            return "What is your check-in date? (format: YYYY-MM-DD)", True
        if not state.checkout:
            return "What is your check-out date? (format: YYYY-MM-DD)", True

        # --- Step 4: Show booking summary and ask for confirmation ---
        state.awaiting_confirmation = True
        return (
            f"Booking summary:\n"
            f"  Hotel:     {state.hotel_name}\n"
            f"  City:      {state.city}\n"
            f"  Check-in:  {state.checkin}\n"
            f"  Check-out: {state.checkout}\n\n"
            f"Would you like to confirm this booking? (yes/no)",
            True
        )

    def _parse_query(self, query: str, state: BookingState) -> None:
        """Extracts city, hotel name, and dates from the user query."""
        import re

        # Extract dates (YYYY-MM-DD)
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", query)
        if dates:
            if not state.checkin:
                state.checkin = dates[0]
            elif not state.checkout:
                state.checkout = dates[0]

        # Extract hotel name
        query_lower = query.lower()
        if not state.hotel_name:
            if "budget inn" in query_lower:
                state.hotel_name = "Budget Inn"
            elif "city hotel" in query_lower:
                state.hotel_name = "City Hotel"
            elif "grand palace" in query_lower:
                state.hotel_name = "Grand Palace"

        # Extract city — simple heuristic: look for "in <City>"
        if not state.city:
            match = re.search(r"\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", query)
            if match:
                state.city = match.group(1)