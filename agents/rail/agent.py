# agents/rail/agent.py

import json
import logging
import os

from utilities.provider_integration.mcp_tool_client import call_mcp_tool

logger = logging.getLogger(__name__)


def _rail_mcp_url() -> str:
    url = os.getenv("RAIL_MCP_URL")
    if not url:
        raise RuntimeError(
            "RAIL_MCP_URL is not set. "
            "Set it to the rail MCP server SSE endpoint (e.g. http://localhost:8004/sse)."
        )
    return url


class RailProviderAgent:
    """Provides rail travel offers and booking simulation via A2A.

    Wraps mcp_servers/rail_server.py behind an A2A interface so that callers
    (BusinessTravelAgent) never need to know the MCP endpoint or port.

    Accepted input — JSON text sent via A2A:
      {"origin": "Dortmund", "destination": "Muenchen", "appointment_time": "Montag um 10 uhr"}
      {"action": "search", "origin": "...", "destination": "...", "appointment_time": "..."}
      {"action": "book", "offer_id": "rail-1"}

    "action" defaults to "search" when omitted.
    Returns a JSON-encoded list of offers (search) or a booking result dict (book).
    Provider agents never engage in multi-turn dialog — input_required is always False.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    async def invoke(self, query: str, context_id: str | None = None) -> tuple[str, bool]:
        logger.info(f"RailProviderAgent received: {query} (context: {context_id})")

        try:
            params = json.loads(query)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": f"Expected JSON input. Got: {query[:200]}"}), False

        action = params.get("action", "search")

        if action == "book":
            result = await self._book_rail_offer(params.get("offer_id", ""))
        else:
            result = await self._search_rail_options(
                params.get("origin", ""),
                params.get("destination", ""),
                params.get("appointment_time", ""),
            )

        return json.dumps(result, ensure_ascii=False), False

    async def _search_rail_options(
        self, origin: str, destination: str, appointment_time: str
    ) -> list[dict]:
        logger.info(f"RailProviderAgent: search {origin} -> {destination} at {appointment_time}")
        return await call_mcp_tool(_rail_mcp_url(), "search_rail_options", {
            "origin": origin,
            "destination": destination,
            "appointment_time": appointment_time,
        })

    async def _book_rail_offer(self, offer_id: str) -> dict:
        logger.info(f"RailProviderAgent: book {offer_id}")
        return await call_mcp_tool(_rail_mcp_url(), "book_rail_offer", {"offer_id": offer_id})
