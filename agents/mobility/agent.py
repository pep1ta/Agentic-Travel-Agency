# agents/mobility/agent.py

import ast
import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)

MOBILITY_MCP_URL = "http://localhost:8006/sse"


class MobilityProviderAgent:
    """Provides airport transfer data via A2A.

    Wraps mcp_servers/mobility_server.py behind an A2A interface so that callers
    (BusinessTravelAgent) never need to know the MCP endpoint or port.

    Accepted input — JSON text sent via A2A:
      {
        "origin": "Dortmund",
        "destination": "Muenchen",
        "departure_airport": "DUS",
        "arrival_airport": "MUC"
      }

    "action" is ignored — this agent only provides transfer data.
    Returns a JSON-encoded dict with transfer details compatible with
    BusinessTravelAgent._combine_flight_with_transfers().
    Provider agents never engage in multi-turn dialog — input_required is always False.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    async def invoke(self, query: str, context_id: str | None = None) -> tuple[str, bool]:
        logger.info(f"MobilityProviderAgent received: {query} (context: {context_id})")

        try:
            params = json.loads(query)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": f"Expected JSON input. Got: {query[:200]}"}), False

        result = await self._get_airport_transfers(
            params.get("origin", ""),
            params.get("destination", ""),
            params.get("departure_airport", ""),
            params.get("arrival_airport", ""),
        )

        return json.dumps(result, ensure_ascii=False), False

    async def _call_mcp_tool(self, tool_name: str, args: dict) -> Any:
        async with sse_client(MOBILITY_MCP_URL) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return self._parse_mcp_result(result)

    def _parse_mcp_result(self, result) -> Any:
        if not result.content:
            return {}
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

    async def _get_airport_transfers(
        self,
        origin: str,
        destination: str,
        departure_airport: str,
        arrival_airport: str,
    ) -> dict:
        logger.info(
            f"MobilityProviderAgent: get transfers {departure_airport} -> {arrival_airport} "
            f"for {origin} -> {destination}"
        )
        return await self._call_mcp_tool("get_airport_transfers", {
            "origin": origin,
            "destination": destination,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
        })
