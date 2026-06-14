# agents/flight/agent.py

import json
import logging
import os

from utilities.provider_integration.mcp_tool_client import call_mcp_tool

logger = logging.getLogger(__name__)


def _flight_mcp_url() -> str:
    url = os.getenv("FLIGHT_MCP_URL")
    if not url:
        raise RuntimeError(
            "FLIGHT_MCP_URL is not set. "
            "Set it to the flight MCP server SSE endpoint (e.g. http://localhost:8005/sse)."
        )
    return url


class FlightProviderAgent:
    """Provides flight travel offers and booking simulation via A2A.

    Wraps mcp_servers/flight_server.py behind an A2A interface so that callers
    (BusinessTravelAgent) never need to know the MCP endpoint or port.

    Accepted input — JSON text sent via A2A:
      {"origin": "Dortmund", "destination": "Wien", "appointment_time": "Montag um 10 uhr"}
      {"action": "search", "origin": "...", "destination": "...", "appointment_time": "..."}
      {"action": "book", "offer_id": "flight-1"}

    "action" defaults to "search" when omitted.
    Returns a JSON-encoded list of flight offers (search) or a booking result dict (book).
    Note: flight offers from this agent have mode="flight", not "flight_with_transfers".
    Transfer enrichment is handled by the BusinessTravelAgent after combining with
    MobilityProviderAgent data.
    Provider agents never engage in multi-turn dialog — input_required is always False.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    async def invoke(self, query: str, context_id: str | None = None) -> tuple[str, bool]:
        logger.info(f"FlightProviderAgent received: {query} (context: {context_id})")

        try:
            params = json.loads(query)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": f"Expected JSON input. Got: {query[:200]}"}), False

        action = params.get("action", "search")

        if action == "book":
            result = await self._book_flight_offer(params.get("offer_id", ""))
        else:
            result = await self._search_flight_options(
                params.get("origin", ""),
                params.get("destination", ""),
                params.get("appointment_time", ""),
            )

        return json.dumps(result, ensure_ascii=False), False

    async def _search_flight_options(
        self, origin: str, destination: str, appointment_time: str
    ) -> list[dict]:
        logger.info(f"FlightProviderAgent: search {origin} -> {destination} at {appointment_time}")
        return await call_mcp_tool(_flight_mcp_url(), "search_flight_options", {
            "origin": origin,
            "destination": destination,
            "appointment_time": appointment_time,
        })

    async def _book_flight_offer(self, offer_id: str) -> dict:
        logger.info(f"FlightProviderAgent: book {offer_id}")
        return await call_mcp_tool(_flight_mcp_url(), "book_flight_offer", {"offer_id": offer_id})
