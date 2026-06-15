# Enterprise Policy Platform — Demo Results

This document summarizes the verified business travel demo scenarios and their outcomes.

## Scenario A: Rail Preferred (Dortmund -> Muenchen)

- Request: `Ich muss Montag um 10 Uhr von Dortmund nach München.`
- A valid rail option under 8 hours exists (RailProviderAgent via RailMCPServer).
- Flight/Mobility enrichment is skipped (policy-aware enrichment).
- `BusinessTravelPolicy` on Sepolia selects `rail-1`.
- No booking or payment is executed automatically.
- Booking requires explicit approval.

## Scenario B: Rail Too Long (Dortmund -> Wien)

- Request: `Ich muss Montag um 10 Uhr von Dortmund nach Wien.`
- RailProviderAgent returns no valid Dortmund -> Wien rail option under 8 hours.
- FlightProviderAgent and MobilityProviderAgent are called.
- BusinessTravelAgent combines flight offer with transfer data: `flight-1-with-transfers`.
- Composition: FlightProviderAgent (carrier + flight offer) + MobilityProviderAgent (transfer data).
- `BusinessTravelPolicy` on Sepolia selects `flight-1-with-transfers`.
- No booking or payment is executed automatically.
- Booking requires explicit approval.

## Scenario C: A2A Multi-Turn Slot Filling

Turn 1:

```text
Ich muss Montag um 10 Uhr in München sein.
```

The agent returns INPUT_REQUIRED and asks for the missing origin.

Turn 2:

```text
Münster
```

Expected result:

- The A2A context remains open between turns.
- Destination München and appointment time from Turn 1 are reused.
- Münster is interpreted as the missing origin.
- Travel planning runs for Münster -> München.
- The final policy selection is still made by `BusinessTravelPolicy` on Sepolia.

Multi-turn only completes missing request data. It does not move the policy decision into the agent or LLM.

## What This Shows

- Provider agents (RailProviderAgent, FlightProviderAgent, MobilityProviderAgent) are discovered at runtime from the on-chain BusinessAgentRegistry.
- `SmartContractClient` calls `BusinessTravelPolicy.selectPolicyCompliantOffer` via `eth_call` — deterministic, read-only, no gas cost.
- If the user approves booking: `BookingClient` sends `createVerifiedBooking` on Sepolia. The contract re-runs the policy on-chain and stores `policyVerified=true` plus an `offerHash`. This is a Sepolia simulation — no real travel booking, no real payment.

## Verification Commands

```powershell
# Unit tests (no blockchain access required)
uv run python test/business_travel/unit/verify_business_travel_unit.py

# Integration: Registry, BTA internals, SmartContractClient (requires ALCHEMY_RPC_URL)
uv run python test/business_travel/integration/verify_business_travel.py

# Integration: Full chain Customer -> Orchestrator -> BusinessTravelAgent (requires running agents)
uv run python test/business_travel/integration/verify_customer_orchestrator_business_travel.py

# Hardhat contract tests (local, no Sepolia required)
npx hardhat test
```

## Hardhat Contract Tests

```text
npx hardhat test
```

Expected: **36 passing**

Covered contract cases:

- BusinessTravelPolicy: rail under 8h wins over flight, long rail allows flight, first class rail invalid,
  flight without transfers invalid, provider reputation below 70 invalid, no valid offer returns NO_SELECTION.
- BusinessTravelBooking: createVerifiedBooking stores policyVerified=true and offerHash,
  mismatched selected_index reverts, booking lifecycle (createVerifiedBooking -> completeBooking).
- BusinessAgentRegistry: agent registration, capability lookup, URI updates.
