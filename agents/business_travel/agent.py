# agents/business_travel/agent.py

import ast
import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

from utilities.smart_contract.smart_contract_client import SmartContractClient

logger = logging.getLogger(__name__)

RAIL_MCP_URL = "http://localhost:8004/sse"
FLIGHT_MCP_URL = "http://localhost:8005/sse"
MOBILITY_MCP_URL = "http://localhost:8006/sse"


class BusinessTravelAgent:
    """Coordinates business travel planning.

    Important architecture rule:
    - MCP servers provide information.
    - This agent coordinates calls and structures the data.
    - SmartContractClient makes the final policy decision.
    - Booking and payment are not executed in version 1.

    Agent != LLM. This class is plain coordination code. A later LLM may help
    understand language or explain the result, but it must not choose the final
    offer itself.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        self._smart_contract = SmartContractClient()

    # -----------------------------------------------------------------------
    # MCP calls
    # -----------------------------------------------------------------------

    async def _call_mcp_tool(self, url: str, tool_name: str, args: dict) -> Any:
        """Calls one MCP tool and returns its parsed result.

        The MCP servers only return travel information. They do not apply the
        business policy and they do not select a winning offer.
        """
        async with sse_client(url) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                return self._parse_mcp_result(result)

    def _parse_mcp_result(self, result) -> Any:
        """Reads an MCP tool result.

        FastMCP usually returns JSON-like text for lists and dictionaries.
        This helper keeps parsing local and simple.
        """
        if not result.content:
            return None

        parsed_items = [self._parse_mcp_text(item.text) for item in result.content]
        if len(parsed_items) == 1:
            return parsed_items[0]
        return parsed_items

    def _parse_mcp_text(self, text: str) -> Any:
        """Parses one text item returned by an MCP tool."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return text

    async def _search_rail_options(self, origin: str, destination: str, appointment_time: str) -> list[dict]:
        """Fetches rail options from the Rail MCP server."""
        return await self._call_mcp_tool(RAIL_MCP_URL, "search_rail_options", {
            "origin": origin,
            "destination": destination,
            "appointment_time": appointment_time,
        })

    async def _search_flight_options(self, origin: str, destination: str, appointment_time: str) -> list[dict]:
        """Fetches flight options from the Flight MCP server."""
        return await self._call_mcp_tool(FLIGHT_MCP_URL, "search_flight_options", {
            "origin": origin,
            "destination": destination,
            "appointment_time": appointment_time,
        })

    async def _get_airport_transfers(
        self,
        origin: str,
        destination: str,
        departure_airport: str,
        arrival_airport: str,
    ) -> dict:
        """Fetches airport transfer information from the Mobility MCP server."""
        return await self._call_mcp_tool(MOBILITY_MCP_URL, "get_airport_transfers", {
            "origin": origin,
            "destination": destination,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
        })

    # -----------------------------------------------------------------------
    # Travel option preparation
    # -----------------------------------------------------------------------

    def _read_request_defaults(self, query: str) -> dict:
        """Interprets the user request with fixed version 1 defaults.

        The query is accepted so this method can later be replaced with simple
        parsing or LLM-assisted language understanding. For now, it deliberately
        returns stable mock values.
        """
        return {
            "origin": "Dortmund",
            "destination": "München",
            "appointment_time": "Monday 10:00",
            "original_query": query,
        }

    def _combine_flight_with_transfers(self, flight: dict, transfers: dict) -> dict:
        """Builds one policy-checkable offer from a flight and transfer data.

        The BusinessTravelAgent only structures information here. It does not
        decide whether this combined offer should win.
        """
        transfers_available = transfers.get("transfers_available") is True

        return {
            "offer_id": f"{flight['offer_id']}-with-transfers",
            "mode": "flight_with_transfers",
            "provider": flight["provider"],
            "total_price": flight["flight_price"] + transfers.get("total_transfer_price", 0),
            "duration_minutes": (
                flight["flight_duration_minutes"]
                + transfers.get("total_transfer_duration_minutes", 0)
            ),
            "travel_class": flight["travel_class"],
            "provider_reputation": flight["provider_reputation"],
            "arrival_buffer_minutes": flight["arrival_buffer_minutes"],
            "transfers_included": transfers_available,
            "departure_airport": flight["departure_airport"],
            "arrival_airport": flight["arrival_airport"],
            "transfer_details": transfers,
        }

    async def _build_offers(self, request: dict) -> list[dict]:
        """Collects rail and flight data and returns policy-checkable offers."""
        rail_options = await self._search_rail_options(
            request["origin"],
            request["destination"],
            request["appointment_time"],
        )
        flight_options = await self._search_flight_options(
            request["origin"],
            request["destination"],
            request["appointment_time"],
        )

        combined_flights = []
        for flight in flight_options:
            transfers = await self._get_airport_transfers(
                request["origin"],
                request["destination"],
                flight["departure_airport"],
                flight["arrival_airport"],
            )
            combined_flights.append(self._combine_flight_with_transfers(flight, transfers))

        return rail_options + combined_flights

    # -----------------------------------------------------------------------
    # Response formatting
    # -----------------------------------------------------------------------

    def _format_offer(self, offer: dict | None) -> str:
        """Formats one offer for a human-readable response."""
        if not offer:
            return "No offer selected."

        return (
            f"{offer['offer_id']} ({offer['mode']})\n"
            f"  Provider: {offer['provider']}\n"
            f"  Price: {offer['total_price']}\n"
            f"  Duration: {offer['duration_minutes']} minutes\n"
            f"  Class: {offer['travel_class']}\n"
            f"  Reputation: {offer['provider_reputation']}\n"
            f"  Arrival buffer: {offer['arrival_buffer_minutes']} minutes"
        )

    def _format_rejections(self, rejected_offers: list[dict]) -> str:
        """Formats rejected offers and their policy reasons."""
        if not rejected_offers:
            return "No rejected offers."

        lines = []
        for rejected in rejected_offers:
            lines.append(f"- {rejected['offer_id']}:")
            for reason in rejected["reasons"]:
                lines.append(f"  - {reason}")
        return "\n".join(lines)

    def _format_decision(self, decision: dict) -> str:
        """Explains the SmartContractClient decision without changing it."""
        return (
            "Business travel policy result\n"
            "============================\n"
            "Final selection made by SmartContractClient policy logic.\n"
            "\n"
            "Selected option:\n"
            f"{self._format_offer(decision['selected_offer'])}\n"
            "\n"
            "Decision reason:\n"
            f"{decision['decision_reason']}\n"
            "\n"
            "Rejected options:\n"
            f"{self._format_rejections(decision['rejected_offers'])}\n"
            "\n"
            "Booking and payment:\n"
            f"booking_requires_approval = {decision['booking_requires_approval']}\n"
            "No booking or payment has been executed."
        )

    # -----------------------------------------------------------------------
    # Main invoke
    # -----------------------------------------------------------------------

    async def invoke(self, query: str, context_id: str | None = None) -> tuple[str, bool]:
        """Processes one business travel request.

        The final selection is delegated to SmartContractClient. This method
        only gathers data, normalizes it, and explains the returned decision.
        """
        logger.info(f"BusinessTravelAgent received: {query} (context: {context_id})")

        request = self._read_request_defaults(query)
        offers = await self._build_offers(request)

        # Final policy selection happens here, in the simulated smart contract
        # client. The agent does not choose the best offer itself.
        decision = self._smart_contract.select_policy_compliant_offer(offers)

        return self._format_decision(decision), False
