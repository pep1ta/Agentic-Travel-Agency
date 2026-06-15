# Agentic Enterprise Policy Platform — Architecture

This document describes the architecture of the enterprise agent coordination prototype with on-chain business travel policy enforcement.

## 1. Goal of the Architecture

The prototype demonstrates controlled agent autonomy in a corporate business travel scenario.

The central idea is:

- Specialized provider agents collect and structure travel offers via MCP servers.
- The BusinessTravelAgent coordinates these agents and prepares an offer bundle.
- The final rule-based selection is made by the deployed `BusinessTravelPolicy` Solidity contract on Sepolia, called from the Python `SmartContractClient` via Web3.
- A booking requires explicit approval and is submitted as a verified Sepolia transaction via `BusinessTravelBooking.createVerifiedBooking`.

The architecture separates coordination from decision authority. Agents act autonomously within the workflow, but the final policy-relevant decision is enforced by on-chain contract logic.

## 2. Core Principle: Agent != LLM

In this prototype, an agent is not the same thing as an LLM.

An agent is a stateful, goal-oriented system component. It receives a task, coordinates calls to other components, structures information, and returns a result.

The LLM is used only for language-related tasks:

- understanding user intent,
- delegating to the right agent,
- explaining results in natural language.

The LLM does not make the final policy decision. The final decision is made by the Solidity `BusinessTravelPolicy` contract deployed on Sepolia.

## 3. Components

### Enterprise Entry Agent (CustomerAgent)

The entry point for internal enterprise requests. It receives user messages and forwards them to the `OrchestratorAgent` via the A2A protocol.

### OrchestratorAgent

Delegates requests to the appropriate specialized agent. For business travel planning, it delegates to the `BusinessTravelAgent`.

### BusinessTravelAgent

Coordinates the business travel workflow. It extracts origin/destination from the user request, discovers provider agents from the on-chain `BusinessAgentRegistry`, calls provider agents via A2A, structures the collected travel offers, and passes the offer bundle to the policy layer.

It does not make the final travel selection.

### RailProviderAgent / FlightProviderAgent / MobilityProviderAgent

Provider agents discovered at runtime from the `BusinessAgentRegistry` on Sepolia. Each agent wraps a dedicated MCP server that provides mock travel data:

- **RailProviderAgent**: mock rail offers from `RailMCPServer`.
- **FlightProviderAgent**: mock flight offers from `FlightMCPServer`.
- **MobilityProviderAgent**: mock airport transfer data from `MobilityMCPServer`.

The `BusinessTravelAgent` combines a flight offer with transfer data to build a `flight_with_transfers` offer when needed.

### SmartContractClient

Calls the deployed `BusinessTravelPolicy` Solidity contract on Sepolia via `eth_call` (read-only, no transaction). Returns `selected_index`, `considered_offers`, `selected_offer`, and a decision reason. No local policy logic — all selection happens on-chain.

### BusinessTravelPolicy (Solidity, Sepolia)

Deployed smart contract that applies the business travel policy deterministically:

- Rail preference: valid rail options (duration <= 480 minutes) win over flights.
- Budget: maximum 600 EUR.
- Travel class: economy or 2nd class only.
- Provider reputation: minimum 70.
- Transfer requirement: flights must include transfers.
- `NO_SELECTION` (`type(uint256).max`) if no offer is policy-compliant.

### BusinessAgentRegistry (Solidity, Sepolia)

On-chain registry that maps capability strings (e.g. `business_travel`, `rail`, `flight`, `mobility`) to agent IDs and A2A URIs. The `BusinessTravelAgent` discovers provider agents from this registry at runtime.

### BookingClient

Submits a Sepolia testnet transaction via `BusinessTravelBooking.createVerifiedBooking`. The contract re-runs `selectPolicyCompliantOffer` on-chain and stores `policyVerified=true` and an `offerHash` in the booking record. This is a simulation — no real travel booking, no real payment.

## 4. Data Flow

```text
User Request
  -> Enterprise Entry Agent (CustomerAgent)
  -> OrchestratorAgent
  -> BusinessTravelAgent
     -> BusinessAgentRegistry (Sepolia, read-only) — discover provider agent IDs and URIs
     -> RailProviderAgent (A2A) -> RailMCPServer
     -> [if no rail <= 480 min]: FlightProviderAgent (A2A) -> FlightMCPServer
     -> [if no rail <= 480 min]: MobilityProviderAgent (A2A) -> MobilityMCPServer
     -> SmartContractClient -> BusinessTravelPolicy.sol (Sepolia, eth_call)
     -> Policy decision (selected_index, selected_offer, considered_offers)
  -> Response with policy decision to user (no booking executed)

[If user explicitly requests booking:]
  -> BookingClient -> BusinessTravelBooking.createVerifiedBooking (Sepolia tx)
  -> Booking result with tx hash and Etherscan link
```

### A2A Multi-Turn Slot Filling

The prototype supports A2A multi-turn for missing request data.

Example:

```text
Turn 1: Ich muss Montag um 10 Uhr in München sein.
Turn 2: Dortmund
```

In Turn 1, the `BusinessTravelAgent` identifies the destination München but the origin is missing. It returns an input-required response and preserves state for the A2A context.

In Turn 2, Dortmund is interpreted as the missing origin. The original destination and appointment time are reused, and planning continues for Dortmund -> München.

Multi-turn only completes missing request data. The governance model is unchanged: the final policy decision is still made by the `BusinessTravelPolicy` contract.

## 5. Policy-aware Enrichment

The `BusinessTravelAgent` uses policy-aware enrichment to avoid unnecessary tool calls.

If a valid rail option (duration <= 480 minutes) exists:

- Flight/Mobility enrichment is skipped.
- Rail options are passed directly to `SmartContractClient`.

If no valid rail option exists:

- Flight options are fetched from `FlightProviderAgent`.
- Airport transfers are fetched from `MobilityProviderAgent`.
- The first economy flight is combined with transfer data into a `flight_with_transfers` offer.
- All offers are passed to `SmartContractClient`.

This optimization decides only which information needs to be prepared before policy evaluation — not which offer wins.

## 6. On-chain / Off-chain Separation

### Off-chain

- User request and natural language processing.
- Agent coordination (A2A protocol).
- MCP server calls and mock travel data.
- Response explanation to the user (LLM-rendered).

### On-chain (Sepolia testnet)

- `BusinessAgentRegistry`: agent discovery by capability.
- `BusinessTravelPolicy`: deterministic policy evaluation via `eth_call`.
- `BusinessTravelBooking`: verified booking record with `policyVerified=true`, `offerHash`, and ETH escrow simulation.

### What is NOT on-chain

- Real travel data or live provider APIs.
- Real payment or real booking confirmation.
- Production identity or settlement infrastructure.

## 7. Verified Scenarios

### Scenario A: Dortmund -> München

- A valid rail option under 8 hours exists.
- Flight/Mobility enrichment is skipped.
- `BusinessTravelPolicy` selects `rail-1`.
- `policyVerified=true` in Sepolia booking simulation.

### Scenario B: Dortmund -> Wien

- No valid rail option under 8 hours exists.
- FlightProviderAgent + MobilityProviderAgent are called.
- A `flight_with_transfers` offer is built.
- `BusinessTravelPolicy` selects `flight-1-with-transfers`.

### Scenario C: Dortmund -> München via Multi-Turn

- Turn 1 provides destination München and appointment time.
- Turn 2 provides the missing origin Dortmund.
- The A2A context is reused.
- Multi-turn does not change the policy selection.

Verified by:

```text
uv run python test/business_travel/unit/verify_business_travel_unit.py
uv run python test/business_travel/integration/verify_business_travel.py
uv run python test/business_travel/integration/verify_customer_orchestrator_business_travel.py
npx hardhat test
```

## 8. Security and Governance

The on-chain policy layer acts as a safety anchor.

It provides:

- technically enforceable selection rules,
- deterministic policy checks independent of agent or LLM behavior,
- separation between information gathering and final decision authority,
- an auditable `offerHash` in the on-chain booking record,
- no booking or payment without explicit user approval.

## 9. Deliberate Limits

The prototype intentionally does not include:

- real travel APIs or live provider data,
- real payment or production settlement,
- production-grade identity, wallet, or KYC infrastructure,
- ERC-8004 or ERC-8183 compliance,
- full travel optimization or multi-leg routing,
- automatic booking without approval.

These limits keep the system focused on the central architectural question: agents coordinate, policy decides.
