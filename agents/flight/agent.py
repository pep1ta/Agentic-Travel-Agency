# agents/flight/agent.py

import ast
import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)

FLIGHT_MCP_URL = "http://localhost:8005/sse"


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

    async def _call_mcp_tool(self, tool_name: str, args: dict) -> Any:
        async with sse_client(FLIGHT_MCP_URL) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return self._parse_mcp_result(result)

    def _parse_mcp_result(self, result) -> Any:
        if not result.content:
            return []
        items = [self._parse_item(item.text) for item in result.content]
        return items[0] if len(items) == 1 else items

    def _parse_item(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return text

    async def _search_flight_options(
        self, origin: str, destination: str, appointment_time: str
    ) -> list[dict]:
        logger.info(f"FlightProviderAgent: search {origin} -> {destination} at {appointment_time}")
        return await self._call_mcp_tool("search_flight_options", {
            "origin": origin,
            "destination": destination,
            "appointment_time": appointment_time,
        })

    async def _book_flight_offer(self, offer_id: str) -> dict:
        logger.info(f"FlightProviderAgent: book {offer_id}")
        return await self._call_mcp_tool("book_flight_offer", {"offer_id": offer_id})
