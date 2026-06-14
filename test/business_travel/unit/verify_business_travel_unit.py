# Run with: uv run python test/business_travel/unit/verify_business_travel_unit.py

"""Unit-level verification for the business travel prototype.

Does NOT require:
  - ALCHEMY_RPC_URL or any Sepolia access
  - Running provider agents
  - OpenAI API key

What this test proves:
  - Multi-turn dialog slot filling (LLM methods stubbed for reproducibility)
  - SmartContractClient policy decisions (deterministic offer bundles)
  - Booking flow handling (submit_verified_booking_for_decision patched)
  - Orchestrator routing logic

BusinessTravelAgent.__init__ calls discover_all_provider_endpoints(use_fallback=False)
which requires ALCHEMY_RPC_URL. In unit tests, this is patched away via _make_agent(),
which injects deterministic endpoint values without any blockchain access.

For the registry-backed E2E test (requires ALCHEMY_RPC_URL + running provider agents):
  uv run python test/business_travel/integration/verify_business_travel.py
"""

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.business_travel.agent import BusinessTravelAgent
from agents.orchestrator.agent import OrchestratorAgent
from test.mocks.mock_smart_contract_client import MockSmartContractClient


# ---------------------------------------------------------------------------
# Deterministic injection helpers for unit tests
# ---------------------------------------------------------------------------

_UNIT_TEST_ENDPOINTS = {
    "rail": ("http://localhost:10010", None),
    "flight": ("http://localhost:10011", None),
    "mobility": ("http://localhost:10012", None),
}


def _make_agent() -> BusinessTravelAgent:
    """Creates a BusinessTravelAgent with patched registry discovery.

    Patches discover_all_provider_endpoints so __init__ receives deterministic
    local endpoints without any ALCHEMY_RPC_URL requirement.
    The agent's _smart_contract is still a real SmartContractClient at this
    point — call _make_unit_agent() to also replace it with the mock.
    """
    with patch(
        "agents.business_travel.agent.discover_all_provider_endpoints",
        return_value=_UNIT_TEST_ENDPOINTS,
    ):
        return BusinessTravelAgent()


def _make_unit_agent(seen_offers: dict) -> BusinessTravelAgent:
    """Creates a fully mocked unit-test agent.

    Patches:
      - discover_all_provider_endpoints → no Sepolia registry call
      - agent._smart_contract → MockSmartContractClient (no contract call)
      - agent._build_offers → deterministic offer bundles
      - LLM methods → deterministic stubs
    """
    agent = _make_agent()
    agent._smart_contract = MockSmartContractClient()
    _attach_deterministic_offer_source(agent, seen_offers)
    _attach_llm_stubs(agent)
    return agent


# ---------------------------------------------------------------------------
# Test assertions and constants
# ---------------------------------------------------------------------------

FORBIDDEN_MODE_CHOICE_PHRASES = [
    "Zug oder Flug",
    "ob Sie mit dem Zug oder Flug",
    "train or flight",
    "transport mode",
]

FORBIDDEN_ENGLISH_IN_GERMAN_RESPONSES = [
    "Please provide",
    "It seems",
    "Could you please",
    "No booking or payment has been executed",
]

DECISION_SECTIONS = [
    "Ausgewählte Option",
    "Gültige Alternativen",
    "Abgelehnte Optionen",
    "Buchung und Zahlung",
]

SCENARIOS = [
    {
        "name": "Dortmund to Munich",
        "query": "Ich muss Montag um 10 Uhr von Dortmund nach Muenchen.",
        "expected_offer_id": "rail-1",
    },
    {
        "name": "Dortmund to Vienna",
        "query": "Ich muss Montag um 10 Uhr von Dortmund nach Wien.",
        "expected_offer_id": "flight-1-with-transfers",
    },
    {
        "name": "Muenster to Munich",
        "query": "Montag um 10 Uhr von Muenster nach Muenchen",
        "expected_offer_id": "rail-muenster-1",
    },
    {
        "name": "Morgen Muenster to Munich",
        "query": "morgen 10 uhr von münster nach münchen",
        "expected_offer_id": "rail-muenster-1",
    },
]


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _normalize_text(text: str) -> str:
    return (
        text.lower()
        .replace("ü", "ue")
        .replace("ä", "ae")
        .replace("ö", "oe")
    )


# ---------------------------------------------------------------------------
# Deterministic offer bundles
# ---------------------------------------------------------------------------

def _offer_bundle_for_request(request: dict) -> list[dict]:
    origin = _normalize_text(str(request.get("origin") or ""))
    destination = _normalize_text(str(request.get("destination") or ""))

    if "dortmund" in origin and "muenchen" in destination:
        return [
            {
                "offer_id": "rail-1",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "InterCity Railways",
                "total_price": 119,
                "duration_minutes": 395,
                "travel_class": "second_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 75,
                "transfers_included": True,
            },
            {
                "offer_id": "rail-2",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "FlexTrack Rail",
                "total_price": 89,
                "duration_minutes": 560,
                "travel_class": "second_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 45,
                "transfers_included": True,
            },
            {
                "offer_id": "rail-3",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "InterCity Railways",
                "total_price": 150,
                "duration_minutes": 390,
                "travel_class": "first_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 90,
                "transfers_included": True,
            },
        ]

    if "dortmund" in origin and "wien" in destination:
        return [
            {
                "offer_id": "rail-vienna-1",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "InterCity Railways",
                "total_price": 139,
                "duration_minutes": 620,
                "travel_class": "second_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 60,
                "transfers_included": True,
            },
            {
                "offer_id": "rail-vienna-3",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "InterCity Railways",
                "total_price": 180,
                "duration_minutes": 470,
                "travel_class": "first_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 90,
                "transfers_included": True,
            },
            {
                "offer_id": "flight-1-with-transfers",
                "mode": "flight_with_transfers",
                "provider": "FlightProviderAgent",
                "carrier": "EuroSky Airlines",
                "total_price": 250,
                "duration_minutes": 185,
                "travel_class": "economy",
                "provider_reputation": 88,
                "arrival_buffer_minutes": 70,
                "transfers_included": True,
            },
            {
                "offer_id": "flight-2-with-transfers",
                "mode": "flight_with_transfers",
                "provider": "FlightProviderAgent",
                "carrier": "BudgetJet Air",
                "total_price": 290,
                "duration_minutes": 190,
                "travel_class": "economy",
                "provider_reputation": 90,
                "arrival_buffer_minutes": 80,
                "transfers_included": True,
            },
        ]

    if "muenster" in origin and "muenchen" in destination:
        return [
            {
                "offer_id": "rail-muenster-1",
                "mode": "rail",
                "provider": "RailProviderAgent",
                "operator": "InterCity Railways",
                "total_price": 129,
                "duration_minutes": 430,
                "travel_class": "second_class",
                "provider_reputation": 82,
                "arrival_buffer_minutes": 70,
                "transfers_included": True,
            }
        ]

    return []


# ---------------------------------------------------------------------------
# Stubs for LLM and offer source
# ---------------------------------------------------------------------------

def _attach_deterministic_offer_source(
    agent: BusinessTravelAgent, seen_offers: dict
) -> None:
    async def fake_build_offers(
        self, origin: str, destination: str, appointment_time: str
    ) -> list[dict]:
        offers = _offer_bundle_for_request({"origin": origin, "destination": destination})
        seen_offers[f"{origin}->{destination}"] = offers
        return offers

    agent._build_offers = types.MethodType(fake_build_offers, agent)


def _attach_llm_stubs(agent: BusinessTravelAgent) -> None:
    # Next Monday from 2026-06-14 (Sunday) = 2026-06-15
    # Used for concrete-date entries below
    QUERY_FIELDS: dict = {
        # --- Complete single-turn plan_trip queries ---
        "ich muss montag um 10 uhr von dortmund nach muenchen.": {
            "intent": "plan_trip", "language": "de",
            "origin": "Dortmund", "destination": "München",
            "appointment_time": "16.06.2026 10:00", "time_mode": "arrival",
        },
        "ich muss montag um 10 uhr von dortmund nach wien.": {
            "intent": "plan_trip", "language": "de",
            "origin": "Dortmund", "destination": "Wien",
            "appointment_time": "16.06.2026 10:00", "time_mode": "arrival",
        },
        "montag um 10 uhr von muenster nach muenchen": {
            "intent": "plan_trip", "language": "de",
            "origin": "Muenster", "destination": "München",
            "appointment_time": "16.06.2026 10:00", "time_mode": "departure",
        },
        "morgen 10 uhr von münster nach münchen": {
            "intent": "plan_trip", "language": "de",
            "origin": "Münster", "destination": "München",
            "appointment_time": "15.06.2026 10:00", "time_mode": "departure",
        },
        # Complete with explicit concrete date
        "ich muss am 24.06.2026 um 10 uhr von dortmund nach münchen": {
            "intent": "plan_trip", "language": "de",
            "origin": "Dortmund", "destination": "München",
            "appointment_time": "24.06.2026 10:00", "time_mode": "arrival",
        },

        # --- Incomplete plan_trip — missing slots must trigger follow-up ---
        "ich muss nach münchen fahren": {
            "intent": "plan_trip", "language": "de",
            "destination": "München",
            # origin + appointment_time absent → follow-up required
        },
        "ich muss nach münchen": {
            "intent": "plan_trip", "language": "de",
            "destination": "München",
            # origin + appointment_time absent → follow-up required
        },
        "ich muss im juni nach münchen": {
            # "im Juni" is not a concrete date → appointment_time stays null
            "intent": "plan_trip", "language": "de",
            "destination": "München",
        },

        # --- slot_fill responses — provide missing slots, merge with existing state ---
        "von dortmund": {
            # Answering "Von wo reisen Sie?" — only origin
            "intent": "slot_fill", "language": "de",
            "origin": "Dortmund",
        },
        "von münster": {
            # Answering "Von wo reisen Sie?" — only origin
            "intent": "slot_fill", "language": "de",
            "origin": "Münster",
        },
        "am 24.06.2026 um 10 uhr": {
            # Answering "Wann?" — only concrete date+time
            "intent": "slot_fill", "language": "de",
            "appointment_time": "24.06.2026 10:00", "time_mode": "departure",
        },
        "von dortmund am 24.06.2026 um 10 uhr": {
            # Answering "Von wo und wann?" — origin + concrete date+time
            "intent": "slot_fill", "language": "de",
            "origin": "Dortmund",
            "appointment_time": "24.06.2026 10:00", "time_mode": "departure",
        },
        "montag um 12 uhr": {
            # Answering "Wann?" with relative weekday+time → concrete date computed
            "intent": "slot_fill", "language": "de",
            "appointment_time": "16.06.2026 12:00", "time_mode": "departure",
        },

        # --- Booking ---
        "buchen": {
            "intent": "book_selected_offer", "language": "de",
        },
    }

    async def fake_update(self, query: str, state) -> dict:
        fields = QUERY_FIELDS.get(query.lower().strip(), {
            "intent": "unknown", "language": state.language or "de",
        })

        lang = fields.get("language", state.language or "de")
        intent = fields.get("intent", "unknown")

        # plan_trip: extract ONLY what's explicitly in the message — no state carry-over.
        # This mirrors the real LLM behavior enforced by the updated system prompt.
        # slot_fill / modify_trip: merge with existing state (slot continuation).
        if intent == "plan_trip":
            merged_origin = fields.get("origin")
            merged_dest = fields.get("destination")
            merged_time = fields.get("appointment_time")
            merged_time_mode = fields.get("time_mode") or "unknown"
        else:
            merged_origin = fields.get("origin") or state.origin
            merged_dest = fields.get("destination") or state.destination
            merged_time = fields.get("appointment_time") or state.appointment_time
            merged_time_mode = fields.get("time_mode") or state.time_mode

        missing: list[str] = []
        if intent not in ("book_selected_offer", "unknown"):
            if not merged_dest:
                missing.append("destination")
            if not merged_origin:
                missing.append("origin")
            if not merged_time:
                missing.append("appointment_time")

        follow_up = None
        if missing:
            if "destination" in missing:
                follow_up = "Wohin möchten Sie reisen?"
            elif "origin" in missing and "appointment_time" in missing:
                follow_up = f"Von welchem Ort starten Sie nach {merged_dest}, und wann?"
            elif "origin" in missing:
                follow_up = f"Von welchem Ort starten Sie nach {merged_dest}?"
            else:
                follow_up = (
                    f"Für welchen Tag und welche Uhrzeit planen Sie die Reise "
                    f"von {merged_origin} nach {merged_dest}?"
                )

        return {
            "intent": intent,
            "language": lang,
            "origin": merged_origin,
            "destination": merged_dest,
            "appointment_time": merged_time,
            "time_mode": merged_time_mode,
            "missing_slots": missing,
            "follow_up_question": follow_up,
            "confidence": 0.95,
        }

    async def fake_render(self, response_type: str, language: str, payload: dict) -> str:
        if response_type == "policy_decision":
            selected = payload.get("selected_offer") or {}
            offer_id = selected.get("offer_id", "?")
            alts = payload.get("valid_alternatives", [])
            rejected = payload.get("rejected_options", payload.get("rejected_offers", []))
            alt_ids = ", ".join(o.get("offer_id", "?") for o in alts) if alts else "Keine."
            rej_ids = ", ".join(o.get("offer_id", "?") for o in rejected) if rejected else "Keine."
            return (
                "Geschäftsreise-Entscheidung\n"
                "===========================\n"
                "Finale Auswahl durch SmartContractClient-Policy-Logik.\n"
                f"Ausgewählte Option: {offer_id}\n"
                f"Gültige Alternativen: {alt_ids}\n"
                f"Abgelehnte Optionen: {rej_ids}\n"
                "Buchung und Zahlung: Genehmigungspflichtig. Noch nicht ausgeführt."
            )
        if response_type == "booking_without_plan":
            return (
                "Bitte planen Sie zuerst eine Reise, damit eine "
                "policy-konforme Option ausgewählt werden kann."
            )
        if response_type == "planning_error":
            return f"Reiseplanung fehlgeschlagen: {payload.get('error', 'unbekannter Fehler')}"
        if response_type == "booking_submitted":
            return (
                "Buchungs-/Zahlungssimulation eingereicht\n"
                f"Ausgewählte Option: {payload.get('selectedOfferId', '?')}\n"
                "Sepolia-Testnet-Simulation. Keine echte Buchung ausgeführt."
            )
        return f"Antwort: {response_type}"

    agent._update_travel_state_with_llm = types.MethodType(fake_update, agent)
    agent._render_user_response_with_llm = types.MethodType(fake_render, agent)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def _assert_german_response(
    response_text: str, failures: list[str], context: str
) -> None:
    for phrase in FORBIDDEN_ENGLISH_IN_GERMAN_RESPONSES:
        _require(
            phrase not in response_text,
            f"{context}: German response contains forbidden English phrase: {phrase}",
            failures,
        )


def _assert_no_transport_mode_question(
    response_text: str, failures: list[str], context: str
) -> None:
    for phrase in FORBIDDEN_MODE_CHOICE_PHRASES:
        _require(
            phrase.lower() not in response_text.lower(),
            f"{context}: agent asked for transport-mode preference: {phrase}",
            failures,
        )


def _assert_decision_sections(
    response_text: str, failures: list[str], context: str
) -> None:
    for section in DECISION_SECTIONS:
        _require(
            section in response_text,
            f"{context}: missing decision transparency section: {section}",
            failures,
        )


def _assert_considered_offers_visible(
    response_text: str,
    offers: list[dict],
    selected_offer_id: str,
    failures: list[str],
    context: str,
) -> None:
    if len(offers) <= 1:
        return
    missing_offer_ids = [
        offer["offer_id"]
        for offer in offers
        if offer["offer_id"] != selected_offer_id and offer["offer_id"] not in response_text
    ]
    _require(
        not missing_offer_ids,
        (
            "Decision transparency cannot be verified because considered offers "
            f"are not exposed. {context} missing: {', '.join(missing_offer_ids)}"
        ),
        failures,
    )


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

async def _verify_regression_scenarios(failures: list[str]) -> None:
    for scenario in SCENARIOS:
        seen_offers: dict = {}
        agent = _make_unit_agent(seen_offers)

        response_text, input_required = await agent.invoke(
            scenario["query"],
            context_id=f"verify-{scenario['name']}",
        )

        _require(
            input_required is False,
            f"{scenario['name']}: complete request should not require more input.",
            failures,
        )
        _require(
            scenario["expected_offer_id"] in response_text,
            f"{scenario['name']}: did not select {scenario['expected_offer_id']}.",
            failures,
        )

        _assert_german_response(response_text, failures, scenario["name"])
        _assert_no_transport_mode_question(response_text, failures, scenario["name"])
        _assert_decision_sections(response_text, failures, scenario["name"])

        offers = next(iter(seen_offers.values()), [])
        _assert_considered_offers_visible(
            response_text,
            offers,
            scenario["expected_offer_id"],
            failures,
            scenario["name"],
        )


async def _verify_incomplete_request_dialog(failures: list[str]) -> None:
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)

    response_text, input_required = await agent.invoke(
        "ich muss nach münchen fahren",
        context_id="verify-incomplete-german",
    )

    _require(
        input_required is True,
        "Incomplete German request should ask for missing slots.",
        failures,
    )
    _assert_german_response(response_text, failures, "Incomplete German request")
    _assert_no_transport_mode_question(response_text, failures, "Incomplete German request")
    _require(
        not seen_offers,
        "Incomplete request should not trigger travel planning.",
        failures,
    )


async def _verify_multiturn_context(failures: list[str]) -> None:
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)
    context_id = "verify-multiturn-dialog"

    turns = [
        "ich muss nach münchen fahren",
        "von münster",
        "montag um 12 uhr",
    ]

    response_text = ""
    input_required = True

    for turn in turns:
        response_text, input_required = await agent.invoke(turn, context_id=context_id)
        _assert_german_response(response_text, failures, f"Multi-turn response for: {turn}")
        _assert_no_transport_mode_question(
            response_text, failures, f"Multi-turn response for: {turn}"
        )

    _require(
        input_required is False,
        "Multi-turn dialog did not complete after origin, destination, and time were provided.",
        failures,
    )
    _require(
        "Geschäftsreise-Entscheidung" in response_text,
        "Multi-turn dialog did not produce a business travel decision.",
        failures,
    )
    _require(
        "rail-muenster-1" in response_text,
        "Multi-turn dialog did not select rail-muenster-1.",
        failures,
    )
    _assert_decision_sections(response_text, failures, "Multi-turn dialog")


async def _verify_booking_intent_without_prior_plan(failures: list[str]) -> None:
    agent = _make_unit_agent({})

    response_text, input_required = await agent.invoke(
        "buchen",
        context_id="verify-buchen-no-plan",
    )

    _require(
        input_required is False,
        "'buchen' without plan should not require further input.",
        failures,
    )
    _require(
        "Reise" in response_text,
        "'buchen' without a prior plan should mention 'Reise' in the error response.",
        failures,
    )
    _assert_german_response(response_text, failures, "'buchen' without prior plan")


async def _verify_booking_intent_with_prior_plan(failures: list[str]) -> None:
    agent = _make_unit_agent({})

    _, _ = await agent.invoke(
        "Ich muss Montag um 10 Uhr von Dortmund nach Muenchen.",
        context_id="verify-buchen-with-plan",
    )

    state = agent._get_state("verify-buchen-with-plan")
    _require(
        state.selected_offer is not None,
        "After planning, state.selected_offer should be set before booking.",
        failures,
    )
    _require(
        state.policy_decision is not None,
        "After planning, state.policy_decision should be set before booking.",
        failures,
    )
    if state.policy_decision is None:
        return

    fake_booking_result = {
        "selectedOfferId": state.selected_offer.get("offer_id", "?"),
        "providerAgentId": "RailProviderAgent",
        "amountEth": "0.0001",
        "selectedIndex": state.policy_decision.get("selected_index", 0),
        "policyVerified": True,
        "status": "submitted",
        "transactionHash": "0xtest123",
        "etherscanUrl": "https://sepolia.etherscan.io/tx/0xtest123",
    }

    async def fake_simulate_booking(self, offer: dict) -> dict:
        return {
            "provider": "RailProviderAgent",
            "providerBookingReference": "SIM-RAIL-1",
            "status": "simulated_confirmed",
            "message": "Provider booking simulation.",
        }

    agent._simulate_provider_booking = types.MethodType(fake_simulate_booking, agent)

    with patch(
        "agents.business_travel.agent.submit_verified_booking_for_decision",
        return_value=fake_booking_result,
    ):
        response_text, input_required = await agent.invoke(
            "buchen",
            context_id="verify-buchen-with-plan",
        )

    _require(
        input_required is False,
        "'buchen' with a plan should not require further input.",
        failures,
    )
    _require(
        "Simulation" in response_text
        or "simulation" in response_text.lower()
        or "Sepolia" in response_text,
        "'buchen' with a plan should mention simulation/Sepolia in response.",
        failures,
    )
    _assert_german_response(response_text, failures, "'buchen' with prior plan")


async def _verify_no_defaults_for_incomplete_request(failures: list[str]) -> None:
    """'ich muss nach münchen' must ask for missing slots — never plan with invented defaults."""
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)

    response_text, input_required = await agent.invoke(
        "ich muss nach münchen",
        context_id="verify-no-defaults",
    )

    _require(
        input_required is True,
        "'ich muss nach münchen' should ask for missing slots, not plan directly.",
        failures,
    )
    _require(
        not seen_offers,
        "'ich muss nach münchen' should not trigger offer fetching.",
        failures,
    )
    state = agent._get_state("verify-no-defaults")
    _require(
        state.origin is None,
        f"origin should be null after 'ich muss nach münchen', got {state.origin!r}",
        failures,
    )
    _require(
        state.appointment_time is None,
        f"appointment_time should be null after 'ich muss nach münchen', got {state.appointment_time!r}",
        failures,
    )
    _require(
        state.destination == "München",
        f"destination should be 'München', got {state.destination!r}",
        failures,
    )
    _assert_german_response(response_text, failures, "No-defaults incomplete request")
    _assert_no_transport_mode_question(response_text, failures, "No-defaults incomplete request")


async def _verify_multiturn_concrete_date(failures: list[str]) -> None:
    """Test 1: step-by-step slot fill with concrete date.
    Turn 1: 'ich muss nach münchen' → follow-up (origin + date/time)
    Turn 2: 'von dortmund'          → follow-up (only date/time)
    Turn 3: 'am 24.06.2026 um 10 uhr' → plans rail-1
    """
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)
    context_id = "verify-multiturn-concrete-date"

    r1, ir1 = await agent.invoke("ich muss nach münchen", context_id=context_id)
    _require(ir1 is True, "Turn 1 should ask for missing slots (origin + time).", failures)
    _require(not seen_offers, "Turn 1 should not trigger planning.", failures)
    s1 = agent._get_state(context_id)
    _require(s1.destination == "München", f"Turn 1: destination should be München, got {s1.destination!r}", failures)
    _require(s1.origin is None, f"Turn 1: origin should be null, got {s1.origin!r}", failures)
    _require(s1.appointment_time is None, f"Turn 1: time should be null, got {s1.appointment_time!r}", failures)

    r2, ir2 = await agent.invoke("von dortmund", context_id=context_id)
    _require(ir2 is True, "Turn 2 should still ask for missing time.", failures)
    s2 = agent._get_state(context_id)
    _require(s2.origin == "Dortmund", f"Turn 2: origin should be Dortmund, got {s2.origin!r}", failures)
    _require(s2.destination == "München", f"Turn 2: destination should still be München, got {s2.destination!r}", failures)
    _require(s2.appointment_time is None, f"Turn 2: time should still be null, got {s2.appointment_time!r}", failures)

    r3, ir3 = await agent.invoke("am 24.06.2026 um 10 uhr", context_id=context_id)
    _require(ir3 is False, "Turn 3 should complete the plan.", failures)
    _require("rail-1" in r3, "Turn 3 should select rail-1 (Dortmund→München).", failures)
    s3 = agent._get_state(context_id)
    _require(
        "24.06.2026" in (s3.appointment_time or ""),
        f"Turn 3: appointment_time should contain '24.06.2026', got {s3.appointment_time!r}",
        failures,
    )
    _assert_decision_sections(r3, failures, "Multiturn concrete date (turn 3)")
    _assert_german_response(r3, failures, "Multiturn concrete date (turn 3)")


async def _verify_combined_slot_fill_concrete_date(failures: list[str]) -> None:
    """Test 2: combined origin + date/time in one slot-fill response.
    Turn 1: 'ich muss nach münchen' → follow-up
    Turn 2: 'von dortmund am 24.06.2026 um 10 uhr' → plans rail-1
    """
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)
    context_id = "verify-combined-slot-fill"

    r1, ir1 = await agent.invoke("ich muss nach münchen", context_id=context_id)
    _require(ir1 is True, "Turn 1 should ask for missing slots.", failures)

    r2, ir2 = await agent.invoke("von dortmund am 24.06.2026 um 10 uhr", context_id=context_id)
    _require(ir2 is False, "Turn 2 (origin + date/time) should complete the plan.", failures)
    _require("rail-1" in r2, "Combined slot fill should select rail-1.", failures)
    s2 = agent._get_state(context_id)
    _require(s2.origin == "Dortmund", f"origin should be Dortmund, got {s2.origin!r}", failures)
    _require("24.06.2026" in (s2.appointment_time or ""), f"time should contain '24.06.2026', got {s2.appointment_time!r}", failures)
    _assert_decision_sections(r2, failures, "Combined slot fill")
    _assert_german_response(r2, failures, "Combined slot fill")


async def _verify_complete_single_turn_concrete_date(failures: list[str]) -> None:
    """Test 3: fully specified request with concrete date plans directly."""
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)

    r, ir = await agent.invoke(
        "ich muss am 24.06.2026 um 10 uhr von dortmund nach münchen",
        context_id="verify-complete-concrete",
    )
    _require(ir is False, "Complete request with concrete date should plan directly.", failures)
    _require("rail-1" in r, "Complete request with date should select rail-1.", failures)
    _assert_decision_sections(r, failures, "Complete single-turn with date")
    _assert_german_response(r, failures, "Complete single-turn with date")


async def _verify_incomplete_month_triggers_followup(failures: list[str]) -> None:
    """Test 4: 'im Juni' is not a concrete date — must ask for origin, day, and time."""
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)

    r, ir = await agent.invoke(
        "ich muss im juni nach münchen",
        context_id="verify-incomplete-month",
    )
    _require(ir is True, "'im Juni' alone is not a complete date — should ask for more.", failures)
    _require(not seen_offers, "'im Juni' should not trigger planning.", failures)
    s = agent._get_state("verify-incomplete-month")
    _require(
        s.appointment_time is None,
        f"appointment_time should be null for 'im Juni', got {s.appointment_time!r}",
        failures,
    )
    _require(s.destination == "München", f"destination should be München, got {s.destination!r}", failures)
    _assert_german_response(r, failures, "Incomplete month follow-up")


async def _verify_new_trip_resets_decision(failures: list[str]) -> None:
    """After a completed trip, a new incomplete request must reset and ask for missing slots."""
    seen_offers: dict = {}
    agent = _make_unit_agent(seen_offers)
    context_id = "verify-reset-after-decision"

    # Turn 1: fully specified trip — plans and sets policy_decision
    response1, input_required1 = await agent.invoke(
        "Ich muss Montag um 10 Uhr von Dortmund nach Muenchen.",
        context_id=context_id,
    )
    _require(
        input_required1 is False,
        "Complete first trip should not require further input.",
        failures,
    )
    state_after_first = agent._get_state(context_id)
    _require(
        state_after_first.policy_decision is not None,
        "State should have policy_decision after first complete trip.",
        failures,
    )

    # Turn 2: new incomplete request — must NOT reuse Dortmund or Montag 10 Uhr
    response2, input_required2 = await agent.invoke(
        "ich muss nach münchen",
        context_id=context_id,
    )

    _require(
        input_required2 is True,
        "After first trip, 'ich muss nach münchen' should ask for missing slots, not plan.",
        failures,
    )
    state_after_second = agent._get_state(context_id)
    _require(
        state_after_second.origin is None,
        f"origin should be reset to null for new trip, got {state_after_second.origin!r}",
        failures,
    )
    _require(
        state_after_second.appointment_time is None,
        f"appointment_time should be reset for new trip, got {state_after_second.appointment_time!r}",
        failures,
    )
    _require(
        state_after_second.policy_decision is None,
        "policy_decision should be cleared when new plan_trip starts.",
        failures,
    )
    _assert_german_response(response2, failures, "New trip after completed trip")
    _assert_no_transport_mode_question(response2, failures, "New trip after completed trip")


def _make_openai_routing_stub(agent_name: str, message: str, final_text: str):
    fake_fn = MagicMock()
    fake_fn.name = "delegate_task"
    fake_fn.arguments = json.dumps({"agent_name": agent_name, "message": message})

    fake_tc = MagicMock()
    fake_tc.id = "stub-tc-1"
    fake_tc.function = fake_fn

    first_msg = MagicMock()
    first_msg.tool_calls = [fake_tc]
    first_msg.content = None
    first_msg.model_dump.return_value = {"role": "assistant"}
    first_choice = MagicMock()
    first_choice.message = first_msg
    first_resp = MagicMock()
    first_resp.choices = [first_choice]

    second_msg = MagicMock()
    second_msg.tool_calls = None
    second_msg.content = final_text
    second_msg.model_dump.return_value = {"role": "assistant", "content": final_text}
    second_choice = MagicMock()
    second_choice.message = second_msg
    second_resp = MagicMock()
    second_resp.choices = [second_choice]

    mock_create = AsyncMock(side_effect=[first_resp, second_resp])
    fake_openai = MagicMock()
    fake_openai.chat.completions.create = mock_create
    return fake_openai


async def _verify_orchestrator_business_travel_routing(failures: list[str]) -> None:
    orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
    orchestrator._active_agent = {}
    orchestrator._last_agent = {}
    orchestrator._last_business_travel_context_id = None
    orchestrator._agent_clients = {"Business Travel Agent": object()}
    orchestrator._mcp_tools = {}
    orchestrator._tools = []
    delegated_messages = []

    async def fake_delegate_task(
        self, agent_name: str, message: str, context_id: str | None = None
    ) -> str:
        delegated_messages.append((agent_name, message, context_id))
        if message == "von münster":
            if context_id:
                self._active_agent[context_id] = agent_name
            return "Wann müssen Sie in München ankommen oder wann möchten Sie losfahren?"
        if message == "montag um 12 uhr":
            if context_id:
                self._active_agent.pop(context_id, None)
                self._last_agent[context_id] = agent_name
            return "Geschäftsreise-Entscheidung\nAusgewählte Option:\nrail-muenster-1"
        if message == "buchen":
            return "Buchungs-/Zahlungssimulation eingereicht"
        return "delegated"

    orchestrator._delegate_task = types.MethodType(fake_delegate_task, orchestrator)
    orchestrator._openai = _make_openai_routing_stub(
        agent_name="Business Travel Agent",
        message="buchen",
        final_text="Buchungs-/Zahlungssimulation eingereicht",
    )

    context_id = "verify-orchestrator-routing"
    orchestrator._active_agent[context_id] = "Business Travel Agent"

    second_response, second_input_required = await orchestrator.invoke(
        "von münster", context_id=context_id,
    )
    third_response, third_input_required = await orchestrator.invoke(
        "montag um 12 uhr", context_id=context_id,
    )
    fourth_response, fourth_input_required = await orchestrator.invoke(
        "buchen", context_id=context_id,
    )

    _require(
        delegated_messages == [
            ("Business Travel Agent", "von münster", context_id),
            ("Business Travel Agent", "montag um 12 uhr", context_id),
            ("Business Travel Agent", "buchen", context_id),
        ],
        "Orchestrator did not delegate context follow-ups unchanged.",
        failures,
    )
    _require(
        second_input_required is True,
        "Orchestrator follow-up should stay in BusinessTravelAgent context.",
        failures,
    )
    _require(
        third_input_required is False,
        "Orchestrator should finish when BusinessTravelAgent finishes.",
        failures,
    )
    _require(
        fourth_input_required is False,
        "Orchestrator short follow-up should not require input by itself.",
        failures,
    )

    for response_text, label in [
        (second_response, "Orchestrator second response"),
        (third_response, "Orchestrator third response"),
        (fourth_response, "Orchestrator fourth response"),
    ]:
        _assert_no_transport_mode_question(response_text, failures, label)
        _assert_german_response(response_text, failures, label)

    _require(
        "Geschäftsreise-Entscheidung" in third_response,
        "Orchestrator routing test did not reach a business travel decision.",
        failures,
    )

    root_instruction = orchestrator._root_instruction()
    root_lower = root_instruction.lower()

    _require(
        "business travel agent" in root_lower and "delegate" in root_lower,
        "Orchestrator prompt does not instruct delegating business travel requests.",
        failures,
    )
    _require(
        "train or flight" in root_lower,
        "Orchestrator prompt does not forbid asking users about train/flight preference.",
        failures,
    )
    _require(
        "smartcontractclient" in root_lower or "not by you" in root_lower,
        "Orchestrator prompt does not state that final selection is made by SmartContractClient.",
        failures,
    )
    _require(
        "cities" in root_lower or "dates" in root_lower or "interpret" in root_lower,
        "Orchestrator prompt does not forbid interpreting cities, dates, or times.",
        failures,
    )


# ---------------------------------------------------------------------------
# Booking path regression
# ---------------------------------------------------------------------------

def _verify_booking_path_is_verified(failures: list[str]) -> None:
    """Ensures the agent source code uses the verified booking path exclusively.

    Checks at the source-code level that:
    - submit_verified_booking_for_decision is imported in agent.py
    - submit_booking_for_offer does not appear in agent.py (dead code removed)
    - create_booking_for_offer does not appear in agent.py
    - create_booking_for_offer does not appear in business_travel_booking_client.py
    - submit_booking_for_offer does not appear in business_travel_booking_client.py
    """
    agent_source_path = Path(__file__).resolve().parents[3] / "agents" / "business_travel" / "agent.py"
    booking_client_path = Path(__file__).resolve().parents[3] / "utilities" / "blockchain" / "business_travel_booking_client.py"

    agent_source = agent_source_path.read_text(encoding="utf-8")
    booking_client_source = booking_client_path.read_text(encoding="utf-8")

    _require(
        "submit_verified_booking_for_decision" in agent_source,
        "agents/business_travel/agent.py does not import submit_verified_booking_for_decision.",
        failures,
    )
    _require(
        "submit_booking_for_offer" not in agent_source,
        "agents/business_travel/agent.py still references submit_booking_for_offer (legacy unverified path).",
        failures,
    )
    _require(
        "create_booking_for_offer" not in agent_source,
        "agents/business_travel/agent.py still references create_booking_for_offer (legacy unverified path).",
        failures,
    )
    _require(
        "submit_booking_for_offer" not in booking_client_source,
        "business_travel_booking_client.py still defines submit_booking_for_offer (should have been deleted).",
        failures,
    )
    _require(
        "create_booking_for_offer" not in booking_client_source,
        "business_travel_booking_client.py still defines create_booking_for_offer (should have been deleted).",
        failures,
    )
    _require(
        "submit_verified_booking_for_decision" in booking_client_source,
        "business_travel_booking_client.py does not define submit_verified_booking_for_decision.",
        failures,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    failures: list[str] = []

    _verify_booking_path_is_verified(failures)
    await _verify_regression_scenarios(failures)
    await _verify_incomplete_request_dialog(failures)
    await _verify_no_defaults_for_incomplete_request(failures)
    await _verify_new_trip_resets_decision(failures)
    await _verify_multiturn_context(failures)
    await _verify_multiturn_concrete_date(failures)
    await _verify_combined_slot_fill_concrete_date(failures)
    await _verify_complete_single_turn_concrete_date(failures)
    await _verify_incomplete_month_triggers_followup(failures)
    await _verify_booking_intent_without_prior_plan(failures)
    await _verify_booking_intent_with_prior_plan(failures)
    await _verify_orchestrator_business_travel_routing(failures)

    if failures:
        print("Business travel unit verification failed.")
        for failure in failures:
            print(f"- {failure}")
        raise AssertionError(f"{len(failures)} business travel unit verification checks failed.")

    print("Booking path: agent uses submit_verified_booking_for_decision exclusively.")
    print("Scenario A selected_offer_id: rail-1")
    print("Scenario B selected_offer_id: flight-1-with-transfers")
    print("Scenario C selected_offer_id: rail-muenster-1")
    print("Scenario D (morgen) selected_offer_id: rail-muenster-1")
    print("'ich muss nach münchen': asks for missing slots, no defaults invented.")
    print("New trip after completed trip: old decision reset, follow-up asked.")
    print("Multi-turn (concrete date, 3 turns): step-by-step slot fill, plans rail-1.")
    print("Combined slot fill (origin+date in one turn): plans rail-1.")
    print("Complete single-turn with concrete date: plans directly, rail-1.")
    print("'im Juni' alone: not a concrete date -- follow-up asked.")
    print("Multi-turn dialog (relative date): slots filled across turns, plan on completion.")
    print("'buchen' without plan: returns German error, no crash.")
    print("'buchen' with prior plan: booking simulation response returned.")
    print("Orchestrator routing: delegates correctly, pass-through verified.")
    print("Business travel unit verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
