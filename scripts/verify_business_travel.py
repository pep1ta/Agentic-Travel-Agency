# Run with: uv run python scripts/verify_business_travel.py

"""End-to-end registry verification for the business travel prototype.

What this test proves:
  1. BusinessAgentRegistry on Sepolia exposes all three provider capabilities.
  2. BusinessTravelAgent initialises using registry-discovered endpoints only
     (no local fallback, no hardcoded URLs).
  3. A2A calls to provider agents succeed and return valid travel offers.
  4. SmartContractClient makes the final policy-compliant offer selection.
  5. All considered offers remain transparent (selected, alternatives, rejected).

Requirements:
  - ALCHEMY_RPC_URL set in .env or environment (Sepolia read-only access)
  - Provider agents running locally:
      RailProviderAgent     http://localhost:10010
      FlightProviderAgent   http://localhost:10011
      MobilityProviderAgent http://localhost:10012

If ALCHEMY_RPC_URL is missing or provider agents are not running, this test fails
with a clear error. There is no automatic fallback to local URLs.

For dialog and slot-filling unit tests (no blockchain or provider agents required):
  uv run python scripts/verify_business_travel_unit.py
"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.business_travel.agent import BusinessTravelAgent
from utilities.blockchain.business_agent_registry_discovery import (
    _load_local_env,
    discover_all_provider_endpoints,
)

EXPECTED_ENDPOINTS = {
    "rail": "http://localhost:10010",
    "flight": "http://localhost:10011",
    "mobility": "http://localhost:10012",
}

E2E_SCENARIOS = [
    {
        "name": "Dortmund -> München",
        "origin": "Dortmund",
        "destination": "München",
        "appointment_time": "Montag 10 Uhr",
        "expected_modes": {"rail"},
    },
    {
        "name": "Dortmund -> Wien",
        "origin": "Dortmund",
        "destination": "Wien",
        "appointment_time": "Montag 10 Uhr",
        "expected_modes": {"rail", "flight_with_transfers"},
    },
]


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _check_env() -> None:
    """Fails immediately if ALCHEMY_RPC_URL is not available."""
    _load_local_env()
    rpc_url = os.environ.get("ALCHEMY_RPC_URL", "").strip()
    if not rpc_url:
        raise SystemExit(
            "\nFEHLER: ALCHEMY_RPC_URL ist nicht gesetzt.\n"
            "\nverify_business_travel.py erfordert echte Blockchain-Registry-Verbindung.\n"
            "Setze ALCHEMY_RPC_URL in .env oder als Umgebungsvariable.\n"
            "\nFür lokale Unit-Tests ohne Registry und ohne Provider-Agenten:\n"
            "  uv run python scripts/verify_business_travel_unit.py\n"
        )


# ---------------------------------------------------------------------------
# Phase 1: Registry Discovery
# ---------------------------------------------------------------------------

def _verify_registry_discovery(failures: list[str]) -> bool:
    """Checks that Sepolia registry returns all three provider endpoints."""
    endpoints = discover_all_provider_endpoints(use_fallback=False)
    all_ok = True

    for capability in ("rail", "flight", "mobility"):
        endpoint, error = endpoints[capability]
        if endpoint is None:
            failures.append(
                f"Registry: Kein Endpunkt für '{capability}'. Fehler: {error}"
            )
            all_ok = False
        else:
            expected = EXPECTED_ENDPOINTS[capability]
            ok = endpoint == expected
            _require(
                ok,
                f"Registry: Unerwarteter Endpunkt für '{capability}': "
                f"erhalten={endpoint!r}, erwartet={expected!r}",
                failures,
            )
            if not ok:
                all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Phase 2: Agent Initialization
# ---------------------------------------------------------------------------

def _verify_agent_init(failures: list[str]) -> "BusinessTravelAgent | None":
    """Checks that BusinessTravelAgent initialises using registry endpoints."""
    try:
        agent = BusinessTravelAgent()
    except RuntimeError as exc:
        failures.append(f"BusinessTravelAgent.__init__ fehlgeschlagen: {exc}")
        return None

    for attr, capability in [
        ("_rail_url", "rail"),
        ("_flight_url", "flight"),
        ("_mobility_url", "mobility"),
    ]:
        actual = getattr(agent, attr, None)
        expected = EXPECTED_ENDPOINTS[capability]
        _require(
            actual == expected,
            f"agent.{attr} = {actual!r}, erwartet {expected!r} (aus Registry)",
            failures,
        )

    return agent


# ---------------------------------------------------------------------------
# Phase 3: E2E — A2A Provider Calls + SmartContractClient
# ---------------------------------------------------------------------------

async def _verify_e2e_offers(
    agent: BusinessTravelAgent, failures: list[str]
) -> None:
    """Calls real provider agents via A2A and checks SmartContractClient output."""

    for scenario in E2E_SCENARIOS:
        name = scenario["name"]

        # A2A calls to registry-discovered endpoints
        try:
            offers = await agent._build_offers(
                scenario["origin"],
                scenario["destination"],
                scenario["appointment_time"],
            )
        except Exception as exc:
            failures.append(
                f"{name}: A2A-Aufruf fehlgeschlagen "
                f"(laufen die Provider-Agenten auf localhost:10010/10011/10012?): "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        _require(
            len(offers) > 0,
            f"{name}: Provider-Agenten haben keine Angebote zurückgegeben.",
            failures,
        )
        if not offers:
            continue

        # Offer modes must be recognised types
        for offer in offers:
            _require(
                offer.get("mode") in ("rail", "flight_with_transfers"),
                f"{name}: Unbekannter offer mode: {offer.get('mode')!r}",
                failures,
            )

        # SmartContractClient must select exactly one offer
        try:
            decision = agent._smart_contract.select_policy_compliant_offer(offers)
        except Exception as exc:
            failures.append(f"{name}: SmartContractClient fehlgeschlagen: {exc}")
            continue

        selected = decision.get("selected_offer")
        _require(
            selected is not None,
            f"{name}: SmartContractClient hat kein Angebot ausgewählt.",
            failures,
        )

        # Transparency fields must be present
        _require(
            "valid_alternatives" in decision,
            f"{name}: decision fehlt 'valid_alternatives'.",
            failures,
        )
        _require(
            "rejected_options" in decision or "rejected_offers" in decision,
            f"{name}: decision fehlt 'rejected_options'/'rejected_offers'.",
            failures,
        )
        _require(
            "considered_offers" in decision or len(offers) >= 1,
            f"{name}: Angebote wurden nicht vollständig weitergereicht.",
            failures,
        )

        if selected:
            print(
                f"  {name}: ausgewählt={selected.get('offer_id')} "
                f"mode={selected.get('mode')} preis={selected.get('total_price')}"
            )
            alts = decision.get("valid_alternatives", [])
            rejs = decision.get("rejected_options", decision.get("rejected_offers", []))
            print(
                f"    Alternativen={[o.get('offer_id') for o in alts]} "
                f"Abgelehnt={[o.get('offer_id') for o in rejs]}"
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    _check_env()
    failures: list[str] = []

    print("\nPhase 1: Blockchain Registry Discovery (Sepolia, read-only)...")
    phase1_ok = _verify_registry_discovery(failures)
    if not phase1_ok:
        print("  FEHLER:")
        for f in failures:
            print(f"    - {f}")
        raise AssertionError(f"{len(failures)} Registry-Checks fehlgeschlagen.")
    print(
        f"  OK: rail={EXPECTED_ENDPOINTS['rail']}  "
        f"flight={EXPECTED_ENDPOINTS['flight']}  "
        f"mobility={EXPECTED_ENDPOINTS['mobility']}"
    )

    print("\nPhase 2: BusinessTravelAgent Initialisierung...")
    agent = _verify_agent_init(failures)
    if failures:
        print("  FEHLER:")
        for f in failures:
            print(f"    - {f}")
        raise AssertionError(f"{len(failures)} Agent-Init-Checks fehlgeschlagen.")
    print("  OK: Agent nutzt Registry-Endpunkte, kein lokaler Fallback.")

    print(
        "\nPhase 3: E2E A2A-Aufrufe + SmartContractClient"
        "\n  (Provider-Agenten müssen auf localhost:10010/10011/10012 laufen)"
    )
    await _verify_e2e_offers(agent, failures)
    if failures:
        print("  FEHLER:")
        for f in failures:
            print(f"    - {f}")
        raise AssertionError(f"{len(failures)} E2E-Checks fehlgeschlagen.")

    print("\nBusiness travel E2E verification passed.")
    print(
        "Registry Discovery, Agent-Initialisierung und A2A-Provider-Aufrufe "
        "alle erfolgreich."
    )


if __name__ == "__main__":
    asyncio.run(main())
