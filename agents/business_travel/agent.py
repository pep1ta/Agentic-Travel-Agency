# agents/business_travel/agent.py

import ast
import json
import logging
import unicodedata
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

from utilities.smart_contract.smart_contract_client import SmartContractClient

logger = logging.getLogger(__name__)

RAIL_MCP_URL = "http://localhost:8004/sse"
FLIGHT_MCP_URL = "http://localhost:8005/sse"
MOBILITY_MCP_URL = "http://localhost:8006/sse"


class TravelPlanningState:
    """Tracks the small multi-turn slot-filling state per A2A context."""

    def __init__(self):
        self.origin: str | None = None
        self.destination: str | None = None
        self.appointment_time: str = "Monday 10:00"
        self.awaiting_origin: bool = False
        self.awaiting_destination: bool = False


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
        self._last_enrichment_note: str | None = None
        self._sessions: dict[str, TravelPlanningState] = {}

    def _get_state(self, context_id: str) -> TravelPlanningState:
        """Returns existing state for a context or creates a new one."""
        if context_id not in self._sessions:
            self._sessions[context_id] = TravelPlanningState()
        return self._sessions[context_id]

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
        logger.info("Before search_rail_options MCP call")
        rail_options = await self._call_mcp_tool(RAIL_MCP_URL, "search_rail_options", {
            "origin": origin,
            "destination": destination,
            "appointment_time": appointment_time,
        })
        logger.info("After search_rail_options MCP call")
        logger.info(f"Rail offers found: {len(rail_options)}")
        return rail_options

    async def _search_flight_options(self, origin: str, destination: str, appointment_time: str) -> list[dict]:
        """Fetches flight options from the Flight MCP server."""
        logger.info("Before search_flight_options MCP call")
        flight_options = await self._call_mcp_tool(FLIGHT_MCP_URL, "search_flight_options", {
            "origin": origin,
            "destination": destination,
            "appointment_time": appointment_time,
        })
        logger.info("After search_flight_options MCP call")
        logger.info(f"Flight offers found: {len(flight_options)}")
        return flight_options

    async def _get_airport_transfers(
        self,
        origin: str,
        destination: str,
        departure_airport: str,
        arrival_airport: str,
    ) -> dict:
        """Fetches airport transfer information from the Mobility MCP server."""
        logger.info(
            f"Before get_airport_transfers MCP call for {departure_airport}->{arrival_airport}"
        )
        transfers = await self._call_mcp_tool(MOBILITY_MCP_URL, "get_airport_transfers", {
            "origin": origin,
            "destination": destination,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
        })
        logger.info(
            f"After get_airport_transfers MCP call for {departure_airport}->{arrival_airport}"
        )
        return transfers

    # -----------------------------------------------------------------------
    # Travel option preparation
    # -----------------------------------------------------------------------

    def _normalize_text(self, text: str) -> str:
        """Normalizes German umlauts enough for the simple demo heuristics."""
        text = text.lower()
        # The second group handles occasional Windows console mojibake such as
        # "MÃ¼nchen" while keeping the heuristic small and explicit.
        text = (
            text.replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
            .replace("ã¼", "ue").replace("ã¤", "ae").replace("ã¶", "oe")
        )
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

    def _parse_query_into_state(self, query: str, state: TravelPlanningState) -> None:
        """Reads origin and destination with a small version 1 heuristic.

        This is deliberately not complex NLP. The user must provide both start
        and destination, for example: "von Dortmund nach Muenchen".
        """
        origin = self._extract_origin(query)
        destination = self._extract_destination(query)

        if origin:
            state.origin = origin
            state.awaiting_origin = False
        if destination:
            state.destination = destination
            state.awaiting_destination = False

        # If the previous turn asked for the origin, a short answer like
        # "Muenster" should fill the missing origin instead of starting over.
        if state.awaiting_origin and not origin:
            short_origin = self._extract_city_answer(query)
            if short_origin:
                state.origin = short_origin
                state.awaiting_origin = False

        if state.awaiting_destination and not destination:
            short_destination = self._extract_city_answer(query)
            if short_destination:
                state.destination = short_destination
                state.awaiting_destination = False

    def _build_request_from_state(self, state: TravelPlanningState) -> dict:
        """Builds the simple request dictionary used by the MCP calls."""
        return {
            "origin": state.origin,
            "destination": state.destination,
            "appointment_time": state.appointment_time,
        }

    def _extract_origin(self, query: str) -> str | None:
        """Extracts the origin with a simple demo heuristic."""
        query_normalized = self._normalize_text(query)
        if "von dortmund" in query_normalized:
            return "Dortmund"
        if "von muenster" in query_normalized or "von m?nster" in query_normalized:
            return "Münster"
        return None

    def _extract_destination(self, query: str) -> str | None:
        """Extracts the destination with a simple demo heuristic."""
        query_normalized = self._normalize_text(query)
        if (
            "nach muenchen" in query_normalized
            or "in muenchen" in query_normalized
            or "nach m?nchen" in query_normalized
            or "in m?nchen" in query_normalized
        ):
            return "München"
        if "nach wien" in query_normalized or "in wien" in query_normalized or "vienna" in query_normalized:
            return "Wien"
        return None

    def _extract_city_answer(self, query: str) -> str | None:
        """Extracts a city from a short follow-up answer."""
        query_normalized = self._normalize_text(query).strip(" .,!?:;")
        if query_normalized == "dortmund":
            return "Dortmund"
        if query_normalized in ["muenster", "m?nster"]:
            return "Münster"
        if query_normalized in ["muenchen", "m?nchen"]:
            return "München"
        if query_normalized in ["wien", "vienna"]:
            return "Wien"
        return None

    def _combine_flight_with_transfers(self, flight: dict, transfers: dict) -> dict:
        """Builds one policy-checkable offer from a flight and transfer data.

        The BusinessTravelAgent only structures information here. It does not
        decide whether this combined offer should win.
        """
        logger.info(f"Before combining flight + transfer for {flight['offer_id']}")
        transfers_available = transfers.get("transfers_available") is True

        combined_offer = {
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
        logger.info(f"After combining flight + transfer for {combined_offer['offer_id']}")
        return combined_offer

    async def _build_offers(self, request: dict) -> list[dict]:
        """Collects rail and flight data and returns policy-checkable offers."""
        self._last_enrichment_note = None

        rail_options = await self._search_rail_options(
            request["origin"],
            request["destination"],
            request["appointment_time"],
        )

        valid_preferred_rail_exists = self._has_policy_relevant_rail_option(rail_options)
        logger.info(f"Valid rail option under 8 hours found: {valid_preferred_rail_exists}")

        if valid_preferred_rail_exists:
            # Rail is preferred by policy in this case. The agent does not make
            # the final choice, but it can avoid unnecessary flight enrichment.
            self._last_enrichment_note = (
                "Flight enrichment skipped because a valid rail option under 8 hours "
                "exists and rail is preferred by policy."
            )
            logger.info(self._last_enrichment_note)
            return rail_options

        flight_options = await self._search_flight_options(
            request["origin"],
            request["destination"],
            request["appointment_time"],
        )

        combined_flights = []
        economy_flights = [
            flight for flight in flight_options
            if flight.get("travel_class") == "economy"
        ]
        logger.info(f"Economy flight offers considered for transfer enrichment: {len(economy_flights)}")

        # Version 1 keeps the fallback simple: if rail cannot win by policy,
        # enrich only the first economy flight with transfers.
        for flight in economy_flights[:1]:
            transfers = await self._get_airport_transfers(
                request["origin"],
                request["destination"],
                flight["departure_airport"],
                flight["arrival_airport"],
            )
            combined_flights.append(self._combine_flight_with_transfers(flight, transfers))

        if combined_flights:
            self._last_enrichment_note = (
                "Flight and transfer enrichment was performed for the first economy "
                "flight because no valid rail option under 8 hours exists."
            )
            logger.info(self._last_enrichment_note)

        return rail_options + combined_flights

    def _has_policy_relevant_rail_option(self, rail_options: list[dict]) -> bool:
        """Checks whether rail can already satisfy the V1 policy preference.

        This is not the final offer selection. It only decides whether expensive
        flight + transfer enrichment is needed before handing offers to the
        SmartContractClient.
        """
        policy = self._smart_contract.get_policy()

        for offer in rail_options:
            if (
                offer.get("mode") == "rail"
                and offer.get("travel_class") == "second_class"
                and offer.get("duration_minutes", 0) <= policy["rail_preferred_max_duration_minutes"]
                and offer.get("total_price", 0) <= policy["max_budget"]
                and offer.get("provider_reputation", 0) >= policy["min_provider_reputation"]
                and offer.get("arrival_buffer_minutes", 0) >= policy["min_arrival_buffer_minutes"]
            ):
                return True

        return False

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
            "Travel data enrichment:\n"
            f"{self._last_enrichment_note or 'Flight and transfer enrichment was performed as needed.'}\n"
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

        context_key = context_id or "default"
        state = self._get_state(context_key)
        self._parse_query_into_state(query, state)

        if not state.origin and state.destination:
            state.awaiting_origin = True
            return "Bitte teilen Sie mir den Startpunkt mit.", True

        if state.origin and not state.destination:
            state.awaiting_destination = True
            return "Bitte teilen Sie mir das Ziel mit.", True

        if not state.origin or not state.destination:
            logger.info("BusinessTravelAgent needs both origin and destination")
            return (
                "Please provide both origin and destination, e.g. "
                "'von Dortmund nach Muenchen'.",
                False,
            )

        request = self._build_request_from_state(state)
        offers = await self._build_offers(request)

        # Final policy selection happens here, in the simulated smart contract
        # client. The agent does not choose the best offer itself.
        logger.info("Before SmartContractClient.select_policy_compliant_offer")
        decision = self._smart_contract.select_policy_compliant_offer(offers)
        logger.info("After SmartContractClient.select_policy_compliant_offer")
        selected_offer = decision.get("selected_offer")
        selected_offer_id = selected_offer.get("offer_id") if selected_offer else None
        logger.info(f"Selected offer_id from SmartContractClient: {selected_offer_id}")

        response = self._format_decision(decision)
        logger.info("BusinessTravelAgent returning final text response")
        del self._sessions[context_key]
        return response, False
