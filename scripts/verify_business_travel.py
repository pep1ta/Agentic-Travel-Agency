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
        "query": "Ich muss Montag um 10 Uhr in Muenchen sein.",
        "expected_offer_id": "rail-1",
    },
    {
        "name": "Scenario B",
        "query": "Ich muss Montag um 10 Uhr in Muenchen sein, but rail is over 8 hours.",
        "expected_offer_id": "flight-1-with-transfers",
    },
]


def _require(condition: bool, message: str) -> None:
    """Raises a clear error if one verification condition fails."""
    if not condition:
        raise AssertionError(message)


async def _run_scenario(agent: BusinessTravelAgent, scenario: dict) -> dict:
    """Runs one scenario through BusinessTravelAgent preparation and policy selection."""
    request = agent._read_request_defaults(scenario["query"])
    offers = await agent._build_offers(request)

    # The final selection still happens in SmartContractClient, not in the agent.
    decision = agent._smart_contract.select_policy_compliant_offer(offers)
    response_text = agent._format_decision(decision)

    return {
        "decision": decision,
        "response_text": response_text,
    }


async def main() -> None:
    """Verifies both business travel demo scenarios."""
    started_processes = await _start_missing_mcp_servers()

    try:
        agent = BusinessTravelAgent()
        checked_offer_ids = {}

        for scenario in SCENARIOS:
            result = await _run_scenario(agent, scenario)
            decision = result["decision"]
            response_text = result["response_text"]
            selected_offer = decision["selected_offer"]
            selected_offer_id = selected_offer["offer_id"] if selected_offer else None

            _require(
                selected_offer_id == scenario["expected_offer_id"],
                (
                    f"{scenario['name']} expected {scenario['expected_offer_id']} "
                    f"but got {selected_offer_id}."
                ),
            )
            _require(
                decision["booking_requires_approval"] is True,
                f"{scenario['name']} did not require booking approval.",
            )
            _require(
                "No booking or payment has been executed." in response_text,
                f"{scenario['name']} does not clearly state that booking/payment was not executed.",
            )

            checked_offer_ids[scenario["name"]] = selected_offer_id

        print(f"Scenario A selected_offer_id: {checked_offer_ids['Scenario A']}")
        print(f"Scenario B selected_offer_id: {checked_offer_ids['Scenario B']}")
        print("Business travel verification passed.")

    finally:
        await _stop_started_servers(started_processes)


if __name__ == "__main__":
    asyncio.run(main())
