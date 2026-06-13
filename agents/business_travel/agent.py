# agents/business_travel/agent.py

import ast
import json
import logging
import re
import unicodedata
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

from utilities.blockchain.business_travel_booking_client import (
    BookingClientError,
    submit_booking_for_offer,
)
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
        self.appointment_time: str | None = None
        self.time_text: str | None = None
        self.day_text: str | None = None
        self.awaiting_origin: bool = False
        self.awaiting_destination: bool = False
        self.awaiting_time: bool = False
        self.awaiting_day: bool = False
        self.selected_offer: dict | None = None
        self.language: str = "en"


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
        """Merges the current user turn into the travel request draft.

        This is deliberately not complex NLP. Every turn may add one or more
        missing fields to the existing draft. We only overwrite a field when
        the new message explicitly contains that field.
        """
        origin = self._extract_origin(query)
        destination = self._extract_destination(query)
        time_text = self._extract_time_text(query)
        day_text = self._extract_day_text(query)
        city_answer = self._extract_city_answer(query)

        if origin:
            state.origin = origin
            state.awaiting_origin = False
        if destination:
            state.destination = destination
            state.awaiting_destination = False
        if time_text:
            state.time_text = time_text
            state.awaiting_time = False
        if day_text:
            state.day_text = day_text
            state.awaiting_day = False

        state.appointment_time = self._compose_appointment_time(state)

        # A short city-only answer fills only a clearly missing slot. This
        # supports follow-ups like "Muenster" without overwriting a complete
        # draft accidentally.
        if city_answer and not origin and not destination:
            if state.awaiting_origin or (not state.origin and state.destination):
                state.origin = city_answer
                state.awaiting_origin = False
            elif state.awaiting_destination or (state.origin and not state.destination):
                state.destination = city_answer
                state.awaiting_destination = False

    def _build_request_from_state(self, state: TravelPlanningState) -> dict:
        """Builds the simple request dictionary used by the MCP calls."""
        canonical_request_text = self._build_canonical_request_text(state)
        return {
            "origin": self._canonical_city_for_tools(state.origin),
            "destination": self._canonical_city_for_tools(state.destination),
            "appointment_time": state.appointment_time,
            "canonical_request_text": canonical_request_text,
        }

    def _build_canonical_request_text(self, state: TravelPlanningState) -> str:
        """Builds a complete request sentence from the multi-turn draft."""
        origin = self._canonical_city_for_tools(state.origin)
        destination = self._canonical_city_for_tools(state.destination)
        appointment_time = state.appointment_time or ""

        if state.time_text and "losfahren" in state.time_text:
            time_without_direction = appointment_time.replace(" losfahren", "")
            return f"{time_without_direction} von {origin} nach {destination} losfahren"

        if state.time_text and "ankommen" in state.time_text:
            time_without_direction = appointment_time.replace(" ankommen", "")
            return f"{time_without_direction} von {origin} nach {destination} ankommen"

        return f"{appointment_time} von {origin} nach {destination}"

    def _canonical_city_for_tools(self, city: str | None) -> str | None:
        """Normalizes city values before they are sent to MCP tools."""
        if not city:
            return None

        city_normalized = self._normalize_text(city)
        if "dortmund" in city_normalized:
            return "Dortmund"
        if "muenster" in city_normalized or "munster" in city_normalized:
            return "Muenster"
        if "muenchen" in city_normalized or "munchen" in city_normalized:
            return "Muenchen"
        if "wien" in city_normalized or "vienna" in city_normalized:
            return "Wien"

        return city

    def _extract_origin(self, query: str) -> str | None:
        """Extracts the origin with a simple demo heuristic."""
        query_normalized = self._normalize_text(query)
        if "von dortmund" in query_normalized:
            return "Dortmund"
        if "von munster" in query_normalized:
            return "Muenster"
        if "von muenchen" in query_normalized or "von munchen" in query_normalized:
            return "Muenchen"
        if "von muenster" in query_normalized or "von m?nster" in query_normalized:
            return "Münster"
        return None

    def _extract_destination(self, query: str) -> str | None:
        """Extracts the destination with a simple demo heuristic."""
        query_normalized = self._normalize_text(query)
        if "nach munchen" in query_normalized or "in munchen" in query_normalized:
            return "Muenchen"
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
        if query_normalized == "munster":
            return "Muenster"
        if query_normalized == "munchen":
            return "Muenchen"
        if query_normalized in ["muenster", "m?nster"]:
            return "Münster"
        if query_normalized in ["muenchen", "m?nchen"]:
            return "München"
        if query_normalized in ["wien", "vienna"]:
            return "Wien"
        return None

    def _extract_day_text(self, query: str) -> str | None:
        """Extracts a simple weekday/date hint for the demo draft."""
        query_normalized = self._normalize_text(query).strip(" .,!?:;")
        if "montag" in query_normalized or query_normalized == "monday":
            return "Montag"
        if "dienstag" in query_normalized or query_normalized == "tuesday":
            return "Dienstag"
        return None

    def _extract_time_text(self, query: str) -> str | None:
        """Extracts a simple time hint without requiring a weekday."""
        query_normalized = self._normalize_text(query).strip(" .,!?:;")

        german_time = re.search(r"(?:um\s+)?(\d{1,2})\s*uhr(?:\s+losfahren)?", query_normalized)
        if german_time:
            hour = german_time.group(1)
            if "losfahren" in query_normalized:
                return f"um {hour} uhr losfahren"
            return f"um {hour} uhr"

        clock_time = re.search(r"\b(\d{1,2}):(\d{2})\b", query_normalized)
        if clock_time:
            return f"{clock_time.group(1)}:{clock_time.group(2)}"

        return None

    def _compose_appointment_time(self, state: TravelPlanningState) -> str | None:
        """Builds the MCP appointment_time only when day and time are known."""
        if state.day_text and state.time_text:
            return f"{state.day_text} {state.time_text}"
        return None

    def _extract_appointment_time(self, query: str) -> str | None:
        """Extracts a simple appointment/departure time for the demo.

        This is not a calendar parser. It only detects the explicit time hints
        used in the demo, for example "Montag um 10 Uhr" or "Monday 10:00".
        """
        query_normalized = self._normalize_text(query)

        if "montag" in query_normalized and ("10 uhr" in query_normalized or "10:00" in query_normalized):
            return "Monday 10:00"

        if "monday" in query_normalized and ("10:00" in query_normalized or "10 am" in query_normalized):
            return "Monday 10:00"

        german_time = re.search(r"\b(\d{1,2})\s*uhr\b", query_normalized)
        if german_time:
            return f"Time {german_time.group(1)}:00"

        clock_time = re.search(r"\b(\d{1,2}):(\d{2})\b", query_normalized)
        if clock_time:
            return f"Time {clock_time.group(1)}:{clock_time.group(2)}"

        return None

    def _is_city_only_follow_up(self, query: str) -> bool:
        """Returns True for a short answer that only names a known city."""
        return self._extract_city_answer(query) is not None

    def _draft_is_complete(self, state: TravelPlanningState) -> bool:
        """Checks whether all required planning slots are present."""
        return bool(state.origin and state.destination and state.appointment_time)

    def _detect_language(self, query: str) -> str:
        """Small language heuristic for the demo response text."""
        query_normalized = self._normalize_text(query)
        german_markers = [
            "ich",
            "muss",
            "von",
            "nach",
            "buchen",
            "montag",
            "dienstag",
            "uhr",
            "bitte",
            "moechte",
            "mochte",
        ]

        if any(marker in f" {query_normalized} " for marker in german_markers):
            return "de"

        return "en"

    def _looks_like_booking_intent(self, query: str) -> bool:
        """Detects a small set of explicit booking intents.

        This is deliberately simple. Booking is only attempted after the user
        clearly asks for it and a policy-selected offer exists in the context.
        """
        query_normalized = self._normalize_text(query).strip(" .,!?:;")
        booking_phrases = [
            "ich moechte buchen",
            "ich mochte buchen",
            "bitte buchen",
            "buchen",
            "option buchen",
            "i want to book",
            "book it",
        ]
        return query_normalized in booking_phrases

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
            "carrier": flight.get("carrier"),
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

        # Version 1 keeps this simple: if rail cannot win by policy, enrich up
        # to two economy flights. We fetch transfers once for the route and
        # reuse the mock transfer data for comparable flight offers.
        transfers = None
        if economy_flights:
            first_flight = economy_flights[0]
            transfers = await self._get_airport_transfers(
                request["origin"],
                request["destination"],
                first_flight["departure_airport"],
                first_flight["arrival_airport"],
            )

        for flight in economy_flights[:2]:
            combined_flights.append(self._combine_flight_with_transfers(flight, transfers))

        if combined_flights:
            self._last_enrichment_note = (
                "Flight and transfer enrichment was performed for the first economy "
                "flight because no valid rail option under 8 hours exists."
            )
            logger.info(self._last_enrichment_note)

        return rail_options + combined_flights

    def _mock_offers_for_known_demo_route(self, request: dict) -> list[dict]:
        """Returns a tiny fallback for the Münster -> München demo route.

        The normal path remains MCP-based. This fallback only keeps the
        multi-turn demo usable when the MCP planning call itself fails. The
        final selection still happens in SmartContractClient.
        """
        origin = self._normalize_text(str(request.get("origin") or ""))
        destination = self._normalize_text(str(request.get("destination") or ""))

        if "muenster" not in origin and "munster" not in origin:
            return []
        if "muenchen" not in destination and "munchen" not in destination:
            return []

        return [
            {
                "offer_id": "rail-muenster-1",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "InterCity Railways",
                "origin": "Muenster Hbf",
                "destination": "Muenchen Hbf",
                "total_price": 129,
                "duration_minutes": 430,
                "travel_class": "second_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 70,
                "transfers_included": True,
                "changes": 1,
                "source": "agent_demo_fallback",
            },
            {
                "offer_id": "rail-muenster-2",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "FlexTrack Rail",
                "origin": "Muenster Hbf",
                "destination": "Muenchen Hbf",
                "total_price": 99,
                "duration_minutes": 590,
                "travel_class": "second_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 45,
                "transfers_included": True,
                "changes": 3,
                "source": "agent_demo_fallback",
            },
        ]

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

    def _format_offer(self, offer: dict | None, language: str = "en") -> str:
        """Formats one offer for a human-readable response."""
        if not offer:
            return "Keine Option ausgewählt." if language == "de" else "No offer selected."

        mode_label = offer["mode"]
        if language == "de":
            if offer["mode"] == "rail":
                mode_label = "Bahn"
            elif offer["mode"] == "flight_with_transfers":
                mode_label = "Flug mit Transfers"

        operator_or_carrier = ""
        if offer.get("operator"):
            label = "Betreiber" if language == "de" else "Operator"
            operator_or_carrier = f"  {label}: {offer['operator']}\n"
        elif offer.get("carrier"):
            label = "Airline" if language == "de" else "Carrier"
            operator_or_carrier = f"  {label}: {offer['carrier']}\n"

        if language == "de":
            return (
                f"{offer['offer_id']} ({mode_label})\n"
                f"  Technischer Provider: {offer['provider']}\n"
                f"{operator_or_carrier}"
                f"  Preis: {offer['total_price']}\n"
                f"  Dauer: {offer['duration_minutes']} Minuten\n"
                f"  Klasse: {offer['travel_class']}\n"
                f"  Reputation: {offer['provider_reputation']}\n"
                f"  Ankunftspuffer: {offer['arrival_buffer_minutes']} Minuten"
            )

        return (
            f"{offer['offer_id']} ({mode_label})\n"
            f"  Provider: {offer['provider']}\n"
            f"{operator_or_carrier}"
            f"  Price: {offer['total_price']}\n"
            f"  Duration: {offer['duration_minutes']} minutes\n"
            f"  Class: {offer['travel_class']}\n"
            f"  Reputation: {offer['provider_reputation']}\n"
            f"  Arrival buffer: {offer['arrival_buffer_minutes']} minutes"
        )

    def _translate_reason(self, reason: str, language: str) -> str:
        """Translates the small set of policy reasons used in the demo."""
        if language != "de":
            return reason

        translations = {
            "Rail offer must have mode == 'rail'.": "Bahnangebot muss mode == 'rail' haben.",
            "Rail offer must be second class.": "Bahnangebot muss zweite Klasse sein.",
            "Rail offer exceeds the maximum budget.": "Bahnangebot überschreitet das Budget.",
            "Rail provider reputation is too low.": "Provider-Reputation des Bahnangebots ist zu niedrig.",
            "Rail arrival buffer is too short.": "Ankunftspuffer des Bahnangebots ist zu kurz.",
            "Flight offer must have mode == 'flight_with_transfers'.": "Flugangebot muss mode == 'flight_with_transfers' haben.",
            "Flight offer must be economy class.": "Flugangebot muss Economy sein.",
            "Flight offer must include transfers to and from the airport.": "Flugangebot muss Transfers zum und vom Flughafen enthalten.",
            "Flight offer exceeds the maximum budget.": "Flugangebot überschreitet das Budget.",
            "Flight provider reputation is too low.": "Provider-Reputation des Flugangebots ist zu niedrig.",
            "Flight arrival buffer is too short.": "Ankunftspuffer des Flugangebots ist zu kurz.",
            "Flight cannot win because a valid rail option under 8 hours exists.": "Flugangebot kann nicht gewinnen, weil eine gültige Bahnoption unter 8 Stunden existiert.",
        }

        translations.update({
            "More expensive than the selected valid rail offer.": "Teurer als die ausgewÃ¤hlte gÃ¼ltige Bahnoption.",
            "More expensive than the selected valid flight offer.": "Teurer als die ausgewÃ¤hlte gÃ¼ltige Flugoption.",
            "More expensive than the selected valid offer.": "Teurer als die ausgewÃ¤hlte gÃ¼ltige Option.",
            "Rail is preferred because a valid rail option under 8 hours exists.": "Bahn wird bevorzugt, weil eine gÃ¼ltige Bahnoption unter 8 Stunden existiert.",
            "Rail is valid but not under the 8-hour rail preference threshold.": "Bahnangebot ist gÃ¼ltig, liegt aber nicht unter der 8-Stunden-PrÃ¤ferenzgrenze.",
            "Not the cheapest valid offer in the allowed policy category.": "Nicht die gÃ¼nstigste gÃ¼ltige Option in der erlaubten Policy-Kategorie.",
        })

        return translations.get(reason, reason)

    def _format_rejections(self, rejected_offers: list[dict], language: str = "en") -> str:
        """Formats rejected offers and their policy reasons."""
        if not rejected_offers:
            return "Keine." if language == "de" else "No rejected offers."

        lines = []
        for rejected in rejected_offers:
            lines.append(f"- {rejected['offer_id']}:")
            for reason in rejected["reasons"]:
                lines.append(f"  - {self._translate_reason(reason, language)}")
        return "\n".join(lines)

    def _format_valid_alternatives(self, decision: dict, language: str = "en") -> str:
        """Formats valid offers that were considered but not selected."""
        alternatives = decision.get("valid_alternatives", [])

        if not alternatives:
            return "Keine." if language == "de" else "None."

        lines = []
        for offer in alternatives:
            lines.append(f"- {self._format_offer(offer, language)}")
            reasons = offer.get("not_selected_reasons", [])
            if language == "de":
                lines.append("  Grund nicht gewÃ¤hlt:")
                for reason in reasons:
                    lines.append(f"    - {self._translate_reason(reason, language)}")
            else:
                lines.append("  Reason not selected:")
                for reason in reasons:
                    lines.append(f"    - {self._translate_reason(reason, language)}")

        return "\n".join(lines)

        lines = []
        for offer in alternatives:
            lines.append(f"- {self._format_offer(offer, language)}")
            if selected_price is not None and offer.get("total_price", 0) > selected_price:
                if language == "de":
                    option_label = "Flugoption" if offer.get("mode") == "flight_with_transfers" else "Option"
                    lines.append("  Grund nicht gewählt:")
                    lines.append(f"    - Teurer als die ausgewählte gültige {option_label}.")
                else:
                    lines.append("  Reason not selected:")
                    lines.append("    - More expensive than the selected valid option.")
            else:
                if language == "de":
                    lines.append("  Grund nicht gewählt:")
                    lines.append("    - Nicht die günstigste gültige Option.")
                else:
                    lines.append("  Reason not selected:")
                    lines.append("    - Not the cheapest valid option.")

        return "\n".join(lines)

    def _format_decision_reason(self, reason: str, language: str) -> str:
        if language != "de":
            return reason

        translations = {
            (
                "A policy-compliant rail offer under 8 hours exists. "
                "Rail is preferred, so the cheapest valid rail offer wins."
            ): (
                "Es gibt ein policy-konformes Bahnangebot unter 8 Stunden. "
                "Bahn wird bevorzugt, deshalb gewinnt das günstigste gültige Bahnangebot."
            ),
            (
                "No policy-compliant rail offer under 8 hours exists. "
                "Flight is allowed, so the cheapest valid flight offer wins."
            ): (
                "Es gibt kein policy-konformes Bahnangebot unter 8 Stunden. "
                "Deshalb sind Flugoptionen erlaubt. Die günstigste gültige Flugoption gewinnt."
            ),
            "No policy-compliant travel offer was found.": (
                "Es wurde keine policy-konforme Reiseoption gefunden."
            ),
        }

        return translations.get(reason, reason)

    def _format_enrichment_note(self, language: str) -> str:
        note = self._last_enrichment_note

        if language != "de":
            return note or "Flight and transfer enrichment was performed as needed."

        if note == (
            "Flight enrichment skipped because a valid rail option under 8 hours "
            "exists and rail is preferred by policy."
        ):
            return (
                "Flug-/Transferanreicherung wurde übersprungen, weil eine gültige "
                "Bahnoption unter 8 Stunden existiert und Bahn laut Policy bevorzugt ist."
            )

        if note == (
            "Flight and transfer enrichment was performed for the first economy "
            "flight because no valid rail option under 8 hours exists."
        ):
            return (
                "Flug- und Transferdaten wurden einbezogen, weil keine gültige "
                "Bahnoption unter 8 Stunden existiert."
            )

        return note or "Flug- und Transferdaten wurden bei Bedarf einbezogen."

    def _format_decision(self, decision: dict, language: str = "en") -> str:
        """Explains the SmartContractClient decision without changing it."""
        if language == "de":
            return (
                "Geschäftsreise-Entscheidung\n"
                "===========================\n"
                "Die finale Auswahl wurde durch die SmartContractClient-Policy-Logik getroffen.\n"
                "\n"
                "Ausgewählte Option:\n"
                f"{self._format_offer(decision['selected_offer'], language)}\n"
                "\n"
                "Entscheidungsgrund:\n"
                f"{self._format_decision_reason(decision['decision_reason'], language)}\n"
                "\n"
                "Datenanreicherung:\n"
                f"{self._format_enrichment_note(language)}\n"
                "\n"
                "Gültige Alternativen:\n"
                f"{self._format_valid_alternatives(decision, language)}\n"
                "\n"
                "Abgelehnte Optionen:\n"
                f"{self._format_rejections(decision.get('rejected_options', decision.get('rejected_offers', [])), language)}\n"
                "\n"
                "Buchung und Zahlung:\n"
                "Eine Buchung ist genehmigungspflichtig.\n"
                "Es wurde noch keine Buchung und keine Zahlung ausgeführt."
            )

        return (
            "Business travel policy result\n"
            "============================\n"
            "Final selection made by SmartContractClient policy logic.\n"
            "\n"
            "Selected option:\n"
            f"{self._format_offer(decision['selected_offer'], language)}\n"
            "\n"
            "Decision reason:\n"
            f"{decision['decision_reason']}\n"
            "\n"
            "Valid alternatives:\n"
            f"{self._format_valid_alternatives(decision, language)}\n"
            "\n"
            "Travel data enrichment:\n"
            f"{self._format_enrichment_note(language)}\n"
            "\n"
            "Rejected options:\n"
            f"{self._format_rejections(decision.get('rejected_options', decision.get('rejected_offers', [])), language)}\n"
            "\n"
            "Booking and payment:\n"
            f"booking_requires_approval = {decision['booking_requires_approval']}\n"
            "No booking or payment has been executed."
        )

    def _format_booking_result(self, booking_result: dict, language: str = "en") -> str:
        """Formats the Sepolia booking/payment simulation result."""
        provider_booking = booking_result.get("providerBooking", {})

        if language == "de":
            return (
                "Buchungs-/Zahlungssimulation eingereicht\n"
                "========================================\n"
                f"Ausgewählte Option: {booking_result['selectedOfferId']}\n"
                f"ProviderAgentId: {booking_result['providerAgentId']}\n"
                f"Betrag: {booking_result['amountEth']} Sepolia ETH\n"
                f"Status: {booking_result['status']}\n"
                f"Transaktion: {booking_result['transactionHash']}\n"
                f"Etherscan: {booking_result['etherscanUrl']}\n"
                "\n"
                "Provider-Buchungssimulation:\n"
                f"Provider: {provider_booking.get('provider', 'nicht verfügbar')}\n"
                f"Buchungsreferenz: {provider_booking.get('providerBookingReference', 'nicht verfügbar')}\n"
                f"Status: {provider_booking.get('status', 'nicht verfügbar')}\n"
                f"Hinweis: {provider_booking.get('message', 'Provider-Buchungssimulation nicht verfügbar.')}\n"
                "\n"
                "Hinweis:\n"
                "Dies ist nur eine Sepolia-Testnet- und Provider-Simulation. "
                "Die finale Confirmation kann später über Etherscan oder ein separates "
                "Check-Script geprüft werden. Es wurde keine echte Reisebuchung ausgeführt."
            )

        return (
            "Sepolia booking/payment simulation submitted\n"
            "============================================\n"
            f"selectedOfferId: {booking_result['selectedOfferId']}\n"
            f"providerAgentId: {booking_result['providerAgentId']}\n"
            f"amountEth: {booking_result['amountEth']}\n"
            f"status: {booking_result['status']}\n"
            f"transactionHash: {booking_result['transactionHash']}\n"
            f"Etherscan: {booking_result['etherscanUrl']}\n"
            "\n"
            "Provider booking simulation:\n"
            f"provider: {provider_booking.get('provider', 'not available')}\n"
            f"providerBookingReference: {provider_booking.get('providerBookingReference', 'not available')}\n"
            f"providerBookingStatus: {provider_booking.get('status', 'not available')}\n"
            f"providerMessage: {provider_booking.get('message', 'Provider booking simulation not available.')}\n"
            "\n"
            "The Booking-/Payment-Simulation was submitted as a Sepolia transaction. "
            "The final confirmation can be checked later via Etherscan or a separate "
            "check script. The provider booking is simulated only. No real travel "
            "booking was executed."
        )

    async def _simulate_provider_booking(self, selected_offer: dict) -> dict:
        """Calls the matching provider MCP booking tool.

        This is only a provider-side simulation. It does not create a real rail
        or flight booking. If the MCP call fails, the Sepolia submission can
        still be reported to the user.
        """
        selected_offer_id = selected_offer.get("id") or selected_offer.get("offer_id")
        mode = selected_offer.get("mode")

        try:
            if mode == "rail":
                return await self._call_mcp_tool(
                    RAIL_MCP_URL,
                    "book_rail_offer",
                    {"offer_id": selected_offer_id},
                )

            if mode == "flight_with_transfers":
                return await self._call_mcp_tool(
                    FLIGHT_MCP_URL,
                    "book_flight_offer",
                    {"offer_id": selected_offer_id},
                )

            return {
                "offerId": selected_offer_id,
                "provider": "not available",
                "status": "not_available",
                "message": f"No provider booking simulation for mode: {mode}",
            }
        except Exception as exc:
            logger.error(f"Provider booking simulation failed: {exc}")
            return {
                "offerId": selected_offer_id,
                "provider": "not available",
                "status": "failed",
                "message": f"Provider booking simulation failed: {exc}",
            }

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
        detected_language = self._detect_language(query)
        if detected_language == "de" or state.language == "en":
            state.language = detected_language

        if self._looks_like_booking_intent(query):
            if not state.selected_offer:
                if state.language == "de":
                    return (
                        "Bitte planen Sie zuerst eine Reise, damit eine "
                        "policy-konforme Option ausgewählt werden kann.",
                        False,
                    )
                return (
                    "Please plan a trip first so a policy-compliant option can be selected.",
                    False,
                )

            try:
                booking_result = submit_booking_for_offer(state.selected_offer)
            except BookingClientError as exc:
                return (
                    f"{exc}\n"
                    "Es wurde keine Sepolia Booking-/Payment-Simulation erstellt.",
                    False,
                )

            booking_result["providerBooking"] = await self._simulate_provider_booking(
                state.selected_offer
            )
            return self._format_booking_result(booking_result, state.language), False

        if self._is_city_only_follow_up(query) and self._draft_is_complete(state):
            if state.language == "de":
                return (
                    "Ich habe bereits eine vollständige Reiseanfrage. Wenn Sie "
                    "die Reise ändern möchten, nennen Sie bitte Start, Ziel und "
                    "Zeitpunkt erneut, z. B. \"Montag um 10 Uhr von Dortmund "
                    "nach Wien\".",
                    False,
                )
            return (
                "I already have a complete travel request. To change it, please "
                "provide origin, destination, and time again.",
                False,
            )

        self._parse_query_into_state(query, state)

        if state.destination and not state.origin and not state.appointment_time:
            state.awaiting_origin = True
            state.awaiting_time = True
            if state.language == "de":
                return (
                    f"Von welchem Ort starten Sie und wann müssen Sie in "
                    f"{state.destination} ankommen oder losfahren?",
                    True,
                )
            return (
                "Please provide the origin and when you need to arrive or depart.",
                True,
            )

        if (
            state.origin
            and state.destination
            and state.time_text
            and not state.day_text
        ):
            state.awaiting_day = True
            if state.language == "de":
                return "Für welchen Tag gilt die Reise? Zum Beispiel: Montag.", True
            return "Which day is this trip for? For example: Monday.", True

        if state.origin and state.destination and not state.appointment_time:
            state.awaiting_time = True
            if state.language == "de":
                return (
                    f"Wann müssen Sie in {state.destination} ankommen oder "
                    "wann möchten Sie losfahren?",
                    True,
                )
            return (
                f"When do you need to arrive in {state.destination}, or when do you want to depart?",
                True,
            )

        if not state.origin and state.destination and state.appointment_time:
            state.awaiting_origin = True
            if state.language == "de":
                return "Von welchem Ort starten Sie? Bitte nennen Sie den Startpunkt.", True
            return "Which city are you starting from?", True

        if state.origin and not state.destination and not state.appointment_time:
            state.awaiting_destination = True
            state.awaiting_time = True
            if state.language == "de":
                return (
                    "Bitte nennen Sie noch das Ziel und wann Sie ankommen "
                    "oder losfahren möchten.",
                    True,
                )
            return (
                "Please provide the destination and when you need to arrive or depart.",
                True,
            )

        if state.origin and not state.destination and state.appointment_time:
            state.awaiting_destination = True
            if state.language == "de":
                return "Bitte teilen Sie mir das Ziel mit.", True
            return "Please provide the destination.", True

        if not state.origin and not state.destination and state.appointment_time:
            state.awaiting_origin = True
            state.awaiting_destination = True
            if state.language == "de":
                return (
                    "Bitte geben Sie sowohl den Abfahrtsort als auch das Ziel an, "
                    "z. B. \"von Dortmund nach München\".",
                    True,
                )
            return (
                "Please provide both origin and destination, e.g. "
                "'von Dortmund nach Muenchen'.",
                True,
            )

        if not state.origin and not state.destination and not state.appointment_time:
            logger.info("BusinessTravelAgent needs origin, destination, and time")
            if state.language == "de":
                return (
                    "Bitte geben Sie Abfahrtsort, Ziel und Zeitpunkt an, "
                    "z. B. \"Montag um 10 Uhr von Dortmund nach München\".",
                    False,
                )
            return (
                "Please provide both origin and destination, e.g. "
                "'von Dortmund nach Muenchen'. Please also provide the time.",
                False,
            )

        if not state.appointment_time:
            state.awaiting_time = True
            if state.language == "de":
                return (
                    "Bitte nennen Sie noch, wann Sie ankommen oder "
                    "losfahren möchten.",
                    True,
                )
            return "Please provide when you need to arrive or depart.", True

        if not state.origin or not state.destination:
            logger.info("BusinessTravelAgent needs origin, destination, and time")
            if state.language == "de":
                return (
                    "Bitte geben Sie Abfahrtsort, Ziel und Zeitpunkt an, "
                    "z. B. \"Montag um 10 Uhr von Dortmund nach München\".",
                    False,
                )
            return (
                "Please provide origin, destination, and time, e.g. "
                "'Monday 10:00 from Dortmund to Munich'.",
                False,
            )

        request = self._build_request_from_state(state)

        try:
            offers = await self._build_offers(request)

            # Final policy selection happens here, in the simulated smart
            # contract client. The agent does not choose the best offer itself.
            logger.info("Before SmartContractClient.select_policy_compliant_offer")
            decision = self._smart_contract.select_policy_compliant_offer(offers)
            logger.info("After SmartContractClient.select_policy_compliant_offer")
            selected_offer = decision.get("selected_offer")
            selected_offer_id = selected_offer.get("offer_id") if selected_offer else None
            logger.info(f"Selected offer_id from SmartContractClient: {selected_offer_id}")
        except Exception as exc:
            logger.error(
                "Business travel planning failed for draft "
                f"{request.get('canonical_request_text')}: {exc}"
            )

            fallback_offers = self._mock_offers_for_known_demo_route(request)
            if fallback_offers:
                logger.info(
                    "Using local demo fallback offers after MCP planning failure "
                    f"for {request.get('canonical_request_text')}"
                )
                decision = self._smart_contract.select_policy_compliant_offer(fallback_offers)
                selected_offer = decision.get("selected_offer")
                selected_offer_id = selected_offer.get("offer_id") if selected_offer else None
                logger.info(
                    f"Selected offer_id from SmartContractClient fallback: {selected_offer_id}"
                )
            else:
                state.selected_offer = None
                debug_text = (
                    f"Debug: origin={request.get('origin')}, "
                    f"destination={request.get('destination')}, "
                    f"time={request.get('appointment_time')}"
                )
                if state.language == "de":
                    return (
                        "Die Reiseplanung konnte mit den aktuellen Angaben nicht "
                        "abgeschlossen werden. Bitte versuchen Sie es mit einer "
                        "vollständigen Angabe wie: \"Montag um 10 Uhr von Münster "
                        f"nach München\".\n{debug_text}",
                        False,
                    )
                return (
                    "The travel planning could not be completed with the current "
                    "details. Please try a complete request such as: \"Monday 10:00 "
                    f"from Muenster to Munich\".\n{debug_text}",
                    False,
                )

        # Keep the policy-selected offer in the A2A context. If the user later
        # explicitly asks to book, this exact offer is used for the Sepolia
        # booking/payment simulation. The agent still does not choose the offer.
        state.selected_offer = selected_offer

        response = self._format_decision(decision, state.language)
        logger.info("BusinessTravelAgent returning final text response")
        return response, False
