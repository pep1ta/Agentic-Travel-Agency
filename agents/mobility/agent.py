# agents/mobility/agent.py

import json
import logging
import os

from utilities.provider_integration.mcp_tool_client import call_mcp_tool

logger = logging.getLogger(__name__)


def _mobility_mcp_url() -> str:
    url = os.getenv("MOBILITY_MCP_URL")
    if not url:
        raise RuntimeError(
            "MOBILITY_MCP_URL is not set. "
            "Set it to the mobility MCP server SSE endpoint (e.g. http://localhost:8006/sse)."
        )
    return url


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
        result = await call_mcp_tool(_mobility_mcp_url(), "get_airport_transfers", {
            "origin": origin,
            "destination": destination,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
        })
        return result if isinstance(result, dict) else {}
