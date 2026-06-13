# Run with: uv run python scripts/verify_business_travel.py

"""Small verification script for the business travel prototype.

This is intentionally not a pytest test suite. The project uses simple demo
scripts, so this file keeps the same didactic style.
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.business_travel.agent import BusinessTravelAgent
from agents.business_travel.demo import _start_missing_mcp_servers, _stop_started_servers


SCENARIOS = [
    {
        "name": "Scenario A",
        "query": "Ich muss Montag um 10 Uhr von Dortmund nach Muenchen.",
        "expected_offer_id": "rail-1",
    },
    {
        "name": "Scenario B",
        "query": "Ich muss Montag um 10 Uhr von Dortmund nach Wien.",
        "expected_offer_id": "flight-1-with-transfers",
    },
]


def _require(condition: bool, message: str) -> None:
    """Raises a clear error if one verification condition fails."""
    if not condition:
        raise AssertionError(message)


async def _run_scenario(agent: BusinessTravelAgent, scenario: dict) -> dict:
    """Runs one scenario through the public BusinessTravelAgent invoke path."""
    response_text, input_required = await agent.invoke(
        scenario["query"],
        context_id=f"verify-{scenario['name']}",
    )

    return {
        "response_text": response_text,
        "input_required": input_required,
    }


async def main() -> None:
    """Verifies both business travel demo scenarios."""
    started_processes = await _start_missing_mcp_servers()

    try:
        agent = BusinessTravelAgent()
        checked_offer_ids = {}

        for scenario in SCENARIOS:
            result = await _run_scenario(agent, scenario)
            response_text = result["response_text"]
            selected_offer_id = scenario["expected_offer_id"]

            _require(
                scenario["expected_offer_id"] in response_text,
                f"{scenario['name']} did not select {scenario['expected_offer_id']}.",
            )
            _require(
                "booking_requires_approval = True" in response_text,
                f"{scenario['name']} did not require booking approval.",
            )
            _require(
                "No booking or payment has been executed." in response_text,
                f"{scenario['name']} does not clearly state that booking/payment was not executed.",
            )

            checked_offer_ids[scenario["name"]] = selected_offer_id

        first_response, first_input_required = await agent.invoke(
            "Ich muss Montag um 10 Uhr in Muenchen sein.",
            context_id="verify-multiturn",
        )
        _require(
            first_input_required is True,
            "Multi-turn first step did not request more input.",
        )
        _require(
            "Startpunkt" in first_response,
            "Multi-turn first step did not ask for the missing origin.",
        )

        second_response, second_input_required = await agent.invoke(
            "Muenster",
            context_id="verify-multiturn",
        )
        _require(
            second_input_required is False,
            "Multi-turn second step did not complete the task.",
        )
        _require(
            "rail-muenster-1" in second_response,
            "Multi-turn scenario did not plan from Muenster to Muenchen.",
        )

        missing_response, missing_input_required = await agent.invoke(
            "Muenster",
            context_id="verify-missing-context",
        )
        _require(
            missing_input_required is False,
            "Single city without context should not open an input-required task.",
        )
        _require(
            "Please provide both origin and destination" in missing_response,
            "Single city without context did not return a clear missing-slots message.",
        )

        print(f"Scenario A selected_offer_id: {checked_offer_ids['Scenario A']}")
        print(f"Scenario B selected_offer_id: {checked_offer_ids['Scenario B']}")
        print("Multi-turn selected_offer_id: rail-muenster-1")
        print("Business travel verification passed.")

    finally:
        await _stop_started_servers(started_processes)


if __name__ == "__main__":
    asyncio.run(main())
