# Run with: uv run python scripts/verify_business_travel.py

"""Verification for the business travel prototype.

This script intentionally stays lightweight instead of introducing pytest.
It verifies dialog and decision principles with deterministic offer bundles,
so it does not depend on locally running MCP servers.
"""

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.business_travel.agent import BusinessTravelAgent
from agents.orchestrator.agent import OrchestratorAgent


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
]


def _require(condition: bool, message: str, failures: list[str]) -> None:
    """Collects verification failures without stopping at the first one."""
    if not condition:
        failures.append(message)


def _normalize_text(text: str) -> str:
    """Small normalization helper for route matching inside this script."""
    return (
        text.lower()
        .replace("ü", "ue")
        .replace("ä", "ae")
        .replace("ö", "oe")
    )


def _offer_bundle_for_request(request: dict) -> list[dict]:
    """Returns deterministic offers for the route under test."""
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


def _attach_deterministic_offer_source(agent: BusinessTravelAgent, seen_offers: dict) -> None:
    """Replaces MCP collection with deterministic offers for verification."""

    async def fake_build_offers(self, request: dict) -> list[dict]:
        offers = _offer_bundle_for_request(request)
        seen_offers[request.get("canonical_request_text", "request")] = offers
        return offers

    agent._build_offers = types.MethodType(fake_build_offers, agent)


def _assert_german_response(response_text: str, failures: list[str], context: str) -> None:
    """Checks that German dialog turns do not fall back to English."""
    for phrase in FORBIDDEN_ENGLISH_IN_GERMAN_RESPONSES:
        _require(
            phrase not in response_text,
            f"{context}: German response contains forbidden English phrase: {phrase}",
            failures,
        )


def _assert_no_transport_mode_question(response_text: str, failures: list[str], context: str) -> None:
    """Checks that the agent does not ask users to choose train vs flight."""
    for phrase in FORBIDDEN_MODE_CHOICE_PHRASES:
        _require(
            phrase.lower() not in response_text.lower(),
            f"{context}: agent asked for transport-mode preference: {phrase}",
            failures,
        )


def _assert_decision_sections(response_text: str, failures: list[str], context: str) -> None:
    """Checks that every decision contains the transparency sections."""
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
    """Checks that considered non-selected offers do not disappear."""
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


async def _verify_regression_scenarios(failures: list[str]) -> None:
    """Checks selected offers and decision transparency for complete requests."""
    for scenario in SCENARIOS:
        agent = BusinessTravelAgent()
        seen_offers = {}
        _attach_deterministic_offer_source(agent, seen_offers)

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
    """Checks that incomplete German requests do not ask for train/flight."""
    agent = BusinessTravelAgent()
    seen_offers = {}
    _attach_deterministic_offer_source(agent, seen_offers)

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
    """Checks that multi-turn slot filling keeps context until decision time."""
    agent = BusinessTravelAgent()
    seen_offers = {}
    _attach_deterministic_offer_source(agent, seen_offers)
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
            response_text,
            failures,
            f"Multi-turn response for: {turn}",
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


def _make_openai_routing_stub(agent_name: str, message: str, final_text: str):
    """Minimal async OpenAI stub for orchestrator routing tests.

    Returns a fake client whose chat.completions.create() yields two responses:
      1. A tool-call response that delegates to agent_name with the given message.
      2. A final text response containing final_text.

    This lets the orchestrator routing test exercise the OpenAI tool-call path
    without making a real network request.
    """
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
    """Checks that active A2A context is routed without semantic parsing."""
    orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
    orchestrator._active_agent = {}
    orchestrator._last_agent = {}
    orchestrator._last_business_travel_context_id = None
    orchestrator._agent_clients = {"Business Travel Agent": object()}
    orchestrator._mcp_tools = {}
    orchestrator._tools = []
    delegated_messages = []

    async def fake_delegate_task(self, agent_name: str, message: str, context_id: str | None = None) -> str:
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

    # The "buchen" turn is not in _active_agent, so the orchestrator falls through
    # to the OpenAI tool-call path. We stub _openai so the test runs without a
    # real network call: the stub returns a single delegate_task tool call followed
    # by a final text response, which is all the routing test needs to verify.
    orchestrator._openai = _make_openai_routing_stub(
        agent_name="Business Travel Agent",
        message="buchen",
        final_text="Buchungs-/Zahlungssimulation eingereicht",
    )

    context_id = "verify-orchestrator-routing"
    orchestrator._active_agent[context_id] = "Business Travel Agent"

    second_response, second_input_required = await orchestrator.invoke(
        "von münster",
        context_id=context_id,
    )
    third_response, third_input_required = await orchestrator.invoke(
        "montag um 12 uhr",
        context_id=context_id,
    )
    fourth_response, fourth_input_required = await orchestrator.invoke(
        "buchen",
        context_id=context_id,
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
    _require(second_input_required is True, "Orchestrator follow-up should stay in BusinessTravelAgent context.", failures)
    _require(third_input_required is False, "Orchestrator should finish when BusinessTravelAgent finishes.", failures)
    _require(fourth_input_required is False, "Orchestrator short follow-up should not require input by itself.", failures)

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

    # Principle 1: Business travel requests must be delegated to the Business Travel Agent.
    # We check for the key concepts rather than a fixed phrase so the prompt wording
    # can evolve without breaking the test.
    _require(
        "business travel agent" in root_lower and "delegate" in root_lower,
        "Orchestrator prompt does not instruct delegating business travel requests to the Business Travel Agent.",
        failures,
    )
    # Principle 2: Orchestrator must not ask about transport mode preference.
    _require(
        "train or flight" in root_lower,
        "Orchestrator prompt does not forbid asking users about train/flight preference.",
        failures,
    )
    # Principle 3: Final travel selection must come from SmartContractClient, not the orchestrator.
    _require(
        "smartcontractclient" in root_lower or "not by you" in root_lower,
        "Orchestrator prompt does not state that final selection is made by SmartContractClient.",
        failures,
    )
    # Principle 4: Orchestrator must not interpret travel slot details (cities, dates, times).
    _require(
        "cities" in root_lower or "dates" in root_lower or "interpret" in root_lower,
        "Orchestrator prompt does not forbid interpreting cities, dates, or times.",
        failures,
    )


async def main() -> None:
    """Runs all verification checks and prints a compact result."""
    failures = []

    await _verify_regression_scenarios(failures)
    await _verify_incomplete_request_dialog(failures)
    await _verify_multiturn_context(failures)
    await _verify_orchestrator_business_travel_routing(failures)

    if failures:
        print("Business travel verification failed.")
        for failure in failures:
            print(f"- {failure}")
        raise AssertionError(f"{len(failures)} business travel verification checks failed.")

    print("Scenario A selected_offer_id: rail-1")
    print("Scenario B selected_offer_id: flight-1-with-transfers")
    print("Scenario C selected_offer_id: rail-muenster-1")
    print("Business travel verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
