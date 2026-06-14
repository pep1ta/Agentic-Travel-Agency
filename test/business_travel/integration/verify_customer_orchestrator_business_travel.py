# Run with: uv run python test/business_travel/integration/verify_customer_orchestrator_business_travel.py

"""Integration test: Delegation chain Customer -> Orchestrator -> BusinessTravelAgent.

Verifies that:
1. OrchestratorAgent (10002) and CustomerAgent (10000) are reachable.
2. OrchestratorAgent delegates a business travel request to BusinessTravelAgent
   (does NOT return "Unknown agent: Business Travel Agent. Available: []").
3. The response contains actual travel data (offers, destinations, policy result)
   including alternatives and rejected options (not just the selected offer).
4. CustomerAgent passes the request through the full chain correctly.
5. An incomplete request ("Ich muss nach München.") triggers a follow-up question,
   never immediate planning with invented defaults.

Requirements:
  - All demo services running:
      powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1
  - OPENAI_API_KEY set in the service environment (Orchestrator uses OpenAI for routing)
  - ALCHEMY_RPC_URL set in .env (BusinessTravelAgent uses Sepolia registry)
"""

import asyncio
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from a2a.client import ClientFactory, ClientConfig
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

ORCHESTRATOR_URL = "http://localhost:10002"
CUSTOMER_URL     = "http://localhost:10000"
BTA_URL          = "http://localhost:10004"
AGENT_CARD_PATH  = "/.well-known/agent-card.json"

TEST_QUERY = "Ich muss am 24.06.2026 um 10 Uhr von Dortmund nach München."

DELEGATION_FAILURE_PATTERNS = [
    "Unknown agent: Business Travel Agent",
    "Available: []",
    "keine spezialisierten Agenten",
    "no specialized agents",
    "no agents available",
]

SUCCESS_INDICATORS = [
    "rail", "bahn",
    "flight", "flug",
    "angebot", "offer",
    "ausgewählt", "selected",
    "dortmund", "münchen", "munchen",
    "rail-1", "flight-1",
]

# Indicators that a full policy decision was returned (alternatives + rejection info)
ALTERNATIVES_INDICATORS = [
    "alternativ", "alternative",
    "abgelehnt", "rejected",
    "gültige", "valid",
]

# Indicators of immediate planning (should NOT appear for incomplete requests)
IMMEDIATE_PLAN_INDICATORS = [
    "rail-1", "flight-1", "ausgewählt", "selected offer",
    "119", "250",  # known prices in test offers
]


def _check_reachable(url: str) -> bool:
    try:
        r = httpx.get(url + AGENT_CARD_PATH, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


async def _send_a2a(base_url: str, text: str) -> str:
    # 120s: Orch makes OpenAI call + BTA delegation + BTA makes 3 provider calls + SmartContractClient
    cfg = ClientConfig(httpx_client=httpx.AsyncClient(timeout=120.0))
    client = await ClientFactory(cfg).create_from_url(base_url)
    request = SendMessageRequest(
        message=Message(
            message_id=uuid.uuid4().hex,
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
            context_id="test-" + uuid.uuid4().hex[:8],
        )
    )
    parts = []
    async for result in client.send_message(request):
        field = result.WhichOneof("payload")
        if field == "message":
            for part in result.message.parts:
                if getattr(part, "text", None):
                    parts.append(part.text)
        elif field == "task":
            if result.task.status.HasField("message"):
                for part in result.task.status.message.parts:
                    if getattr(part, "text", None):
                        parts.append(part.text)
    return "\n".join(parts)


async def _send_a2a_with_context(
    base_url: str, text: str, context_id: str
) -> tuple[str, bool]:
    """Sends one message with a fixed context_id. Returns (text, input_required)."""
    cfg = ClientConfig(httpx_client=httpx.AsyncClient(timeout=120.0))
    client = await ClientFactory(cfg).create_from_url(base_url)
    request = SendMessageRequest(
        message=Message(
            message_id=uuid.uuid4().hex,
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
            context_id=context_id,
        )
    )
    parts = []
    input_required = False
    async for result in client.send_message(request):
        field = result.WhichOneof("payload")
        if field == "message":
            for part in result.message.parts:
                if getattr(part, "text", None):
                    parts.append(part.text)
        elif field == "task":
            if result.task.status.HasField("message"):
                for part in result.task.status.message.parts:
                    if getattr(part, "text", None):
                        parts.append(part.text)
            if result.task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                input_required = True
    return "\n".join(parts), input_required


def _check_response(label: str, response: str, failures: list[str]) -> bool:
    for pattern in DELEGATION_FAILURE_PATTERNS:
        if pattern.lower() in response.lower():
            failures.append(
                f"{label}: Delegation fehlgeschlagen - Antwort enthaelt {pattern!r}. "
                "BusinessTravelAgent ist nicht in _agent_clients registriert."
            )
            return False
    has_data = any(ind.lower() in response.lower() for ind in SUCCESS_INDICATORS)
    if not has_data:
        failures.append(
            f"{label}: Antwort enthaelt keine erkennbaren Reisedaten. "
            f"Erhalten: {response[:250]!r}"
        )
        return False
    return True


async def main() -> None:
    failures: list[str] = []

    print("\nPhase 1: Erreichbarkeit pruefen...")
    orch_ok = _check_reachable(ORCHESTRATOR_URL)
    cust_ok = _check_reachable(CUSTOMER_URL)

    print(f"  {'[OK]  ' if orch_ok else '[FAIL]'} OrchestratorAgent  {ORCHESTRATOR_URL}")
    print(f"  {'[OK]  ' if cust_ok else '[FAIL]'} CustomerAgent       {CUSTOMER_URL}")

    if not orch_ok or not cust_ok:
        print("\nFEHLER: Agenten nicht erreichbar.")
        print("Bitte zuerst starten:")
        print("  powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1")
        raise SystemExit(1)

    print(f"\nPhase 2: OrchestratorAgent-Delegation (direkt auf :10002)...")
    print(f"  Query: {TEST_QUERY!r}")
    try:
        orch_response = await _send_a2a(ORCHESTRATOR_URL, TEST_QUERY)
    except Exception as exc:
        failures.append(f"OrchestratorAgent A2A-Aufruf fehlgeschlagen: {type(exc).__name__}: {exc}")
        orch_response = ""

    if orch_response:
        print(f"  Response (first 300 chars): {orch_response[:300]!r}")
        if _check_response("OrchestratorAgent", orch_response, failures):
            print("  [OK] Delegation zu BusinessTravelAgent erfolgreich, Reisedaten in Antwort.")
        has_alts = any(ind.lower() in orch_response.lower() for ind in ALTERNATIVES_INDICATORS)
        if not has_alts:
            failures.append(
                "Phase 2 (OrchestratorAgent): Antwort enthaelt keine Alternativen/Ablehnungsinfos. "
                "Orchestrator fasst BTA-Antwort moeglicherweise neu zusammen statt direkt "
                f"weiterzuleiten. Erhalten: {orch_response[:200]!r}"
            )
        else:
            print("  [OK] Alternativen und/oder abgelehnte Optionen in Antwort enthalten.")
    else:
        if not any("OrchestratorAgent" in f for f in failures):
            failures.append("OrchestratorAgent: leere Antwort erhalten.")

    print(f"\nPhase 3: CustomerAgent-Vollkette (:10000 -> :10002 -> :10004)...")
    print(f"  Query: {TEST_QUERY!r}")
    try:
        cust_response = await _send_a2a(CUSTOMER_URL, TEST_QUERY)
    except Exception as exc:
        failures.append(f"CustomerAgent A2A-Aufruf fehlgeschlagen: {type(exc).__name__}: {exc}")
        cust_response = ""

    if cust_response:
        print(f"  Response (first 300 chars): {cust_response[:300]!r}")
        if _check_response("CustomerAgent", cust_response, failures):
            print("  [OK] Vollkette Customer -> Orchestrator -> BusinessTravelAgent funktioniert.")
        has_alts = any(ind.lower() in cust_response.lower() for ind in ALTERNATIVES_INDICATORS)
        if not has_alts:
            failures.append(
                "Phase 3 (CustomerAgent): Antwort enthaelt keine Alternativen/Ablehnungsinfos. "
                f"Erhalten: {cust_response[:200]!r}"
            )
        else:
            print("  [OK] Alternativen und/oder abgelehnte Optionen in CustomerAgent-Antwort.")
    else:
        if not any("CustomerAgent" in f for f in failures):
            failures.append("CustomerAgent: leere Antwort erhalten.")

    print(f"\nPhase 4: Unvollstaendige Anfrage soll Rueckfrage ausloesen, nicht direkt planen...")
    incomplete_query = "Ich muss nach München."
    print(f"  Query: {incomplete_query!r}")
    try:
        orch_incomplete = await _send_a2a(ORCHESTRATOR_URL, incomplete_query)
    except Exception as exc:
        failures.append(f"Phase 4 A2A-Aufruf fehlgeschlagen: {type(exc).__name__}: {exc}")
        orch_incomplete = ""

    if orch_incomplete:
        print(f"  Response (first 300 chars): {orch_incomplete[:300]!r}")
        for pattern in DELEGATION_FAILURE_PATTERNS:
            if pattern.lower() in orch_incomplete.lower():
                failures.append(f"Phase 4: Delegation fehlgeschlagen: {pattern}")
        has_plan = any(ind.lower() in orch_incomplete.lower() for ind in IMMEDIATE_PLAN_INDICATORS)
        if has_plan:
            failures.append(
                "Phase 4: Unvollstaendige Anfrage 'Ich muss nach München.' hat sofort geplant "
                "(Antwort enthaelt Angebots-IDs oder Preise). Fehlende Slots sollen erfragt werden. "
                f"Erhalten: {orch_incomplete[:200]!r}"
            )
        else:
            print("  [OK] Unvollstaendige Anfrage loeste Rueckfrage aus, keine sofortige Planung.")
    else:
        failures.append("Phase 4: Keine Antwort auf unvollstaendige Anfrage erhalten.")

    print(f"\nPhase 5: Multi-Turn-Slot-Filling direkt auf BusinessTravelAgent (:10004)...")
    mt_ctx = "test-multiturn-" + uuid.uuid4().hex[:8]

    mt_q1 = "Ich muss nach München."
    print(f"  Turn 1: {mt_q1!r}")
    try:
        mt_r1, mt_ir1 = await _send_a2a_with_context(BTA_URL, mt_q1, mt_ctx)
    except Exception as exc:
        failures.append(f"Phase 5 Turn 1 fehlgeschlagen: {type(exc).__name__}: {exc}")
        mt_r1, mt_ir1 = "", False

    if mt_r1:
        print(f"  Turn 1 Antwort: {mt_r1[:120]!r}  input_required={mt_ir1}")
        if not mt_ir1:
            failures.append(
                f"Phase 5 Turn 1: BTA haette nach fehlenden Slots fragen sollen (input_required=True), "
                f"geplant stattdessen direkt. Antwort: {mt_r1[:200]!r}"
            )
        else:
            print("  [OK] Turn 1: BTA fragt nach Startort und/oder Datum/Uhrzeit.")

            mt_q2 = "Von Dortmund am 24.06.2026 um 10 Uhr."
            print(f"  Turn 2: {mt_q2!r}")
            try:
                mt_r2, mt_ir2 = await _send_a2a_with_context(BTA_URL, mt_q2, mt_ctx)
            except Exception as exc:
                failures.append(f"Phase 5 Turn 2 fehlgeschlagen: {type(exc).__name__}: {exc}")
                mt_r2, mt_ir2 = "", False

            if mt_r2:
                print(f"  Turn 2 Antwort (first 200): {mt_r2[:200]!r}  input_required={mt_ir2}")
                if mt_ir2:
                    failures.append(
                        f"Phase 5 Turn 2: BTA haette nach Startort + Datum planen sollen, "
                        f"fragt aber erneut nach Slots. Antwort: {mt_r2[:200]!r}"
                    )
                else:
                    has_data = any(ind.lower() in mt_r2.lower() for ind in SUCCESS_INDICATORS)
                    if not has_data:
                        failures.append(
                            f"Phase 5 Turn 2: Keine Reisedaten in BTA-Antwort. "
                            f"Erhalten: {mt_r2[:200]!r}"
                        )
                    else:
                        print("  [OK] Turn 2: BTA hat geplant, Reisedaten in Antwort.")
                        has_alts = any(ind.lower() in mt_r2.lower() for ind in ALTERNATIVES_INDICATORS)
                        if has_alts:
                            print("  [OK] Turn 2: Alternativen/Ablehnungsinfos in BTA-Antwort.")
                        else:
                            failures.append(
                                f"Phase 5 Turn 2: Keine Alternativen/Ablehnungsinfos. "
                                f"Erhalten: {mt_r2[:200]!r}"
                            )
            else:
                failures.append("Phase 5 Turn 2: Keine Antwort erhalten.")
    else:
        failures.append("Phase 5 Turn 1: Keine Antwort erhalten.")

    if failures:
        print("\nFEHLER:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)

    print("\nCustomer/Orchestrator/BusinessTravelAgent Integrationskette: BESTANDEN")
    print("OrchestratorAgent delegiert korrekt an BusinessTravelAgent.")
    print("Alternativen und Ablehnungsinfos vollstaendig in Antwort.")
    print("CustomerAgent leitet korrekt durch die vollstaendige Kette.")
    print("Unvollstaendige Anfrage loest Rueckfrage aus, keine Defaults erfunden.")
    print("BTA Multi-Turn direkt: Slots korrekt gemerged, Planung nach vollstaendigem Fill.")


if __name__ == "__main__":
    asyncio.run(main())
