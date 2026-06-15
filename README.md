# Agentic Enterprise Policy Platform

A prototype for smart-contract-governed enterprise agent coordination. Specialized agents collect and structure business travel offers; the final policy-compliant selection is made by a Solidity contract deployed on Sepolia, called from Python via Web3.

Example request:

```text
Ich muss Montag um 10 Uhr von Dortmund nach München.
```

The system discovers provider agents from an on-chain registry, collects travel offers, builds an offer bundle, and delegates the final selection to `BusinessTravelPolicy.selectPolicyCompliantOffer` on Sepolia — deterministic, on-chain, not by an LLM.

---

## Documentation

- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Architecture diagram: [`docs/architecture_diagram.md`](docs/architecture_diagram.md)
- Demo results: [`docs/demo_results.md`](docs/demo_results.md)
- Thesis mapping: [`docs/thesis_mapping.md`](docs/thesis_mapping.md)
- Operations guide: [`ops/README.md`](ops/README.md)

---

## System Flow

```text
Enterprise User
  -> Enterprise Entry Agent  (CustomerAgent :10000)
  -> OrchestratorAgent       (:10002)
  -> BusinessTravelAgent     (:10004)
     -> BusinessAgentRegistry (Sepolia, read-only)  — agent discovery
     -> RailProviderAgent    (:10010)  -> RailMCPServer    (:8004)
     -> FlightProviderAgent  (:10011)  -> FlightMCPServer  (:8005)   [if no rail <= 8h]
     -> MobilityProviderAgent(:10012)  -> MobilityMCPServer(:8006)   [if no rail <= 8h]
     -> SmartContractClient
           -> BusinessTravelPolicy.sol (Sepolia, eth_call)
     -> Policy decision (selected offer, alternatives, rejected offers)
  -> Response to user  (no booking executed)

[User approves booking:]
  -> BookingClient
     -> BusinessTravelBooking.createVerifiedBooking (Sepolia tx)
     -> policyVerified=true, offerHash stored on-chain
```

---

## Architecture Principles

**Agent != LLM.** An agent is a stateful, goal-oriented component that coordinates tools and other agents. The LLM assists with language understanding and explanation only — it does not make the final policy selection.

**Policy-aware enrichment.** If a valid rail option (duration <= 480 minutes) exists, the BusinessTravelAgent skips Flight/Mobility enrichment entirely. The policy prefers rail; fetching flight data would be wasteful and misleading.

**Dual verification.** The Python `SmartContractClient` calls `BusinessTravelPolicy` via `eth_call` (off-chain read) to determine which offer to select. When the user approves booking, `BusinessTravelBooking.createVerifiedBooking` re-runs the same policy on-chain inside the transaction, stores `policyVerified=true` and an `offerHash`. No manipulation between policy evaluation and booking is possible.

**Registry-based agent discovery.** Provider agent IDs and A2A URIs are resolved at runtime from the `BusinessAgentRegistry` on Sepolia — no hardcoded IDs.

---

## Policy Rules (BusinessTravelPolicy.sol)

- Rail is preferred when a valid option with `duration_minutes <= 480` exists.
- Rail must be 2nd class (economy); first class is rejected.
- Flight must be economy class.
- Flight must include airport transfers (`flight_with_transfers`); standalone flights are rejected.
- Maximum total price: 600 EUR.
- Minimum provider reputation score: 70.
- `NO_SELECTION` (`type(uint256).max`) is returned when no offer passes all rules.

---

## Project Structure

```text
agents/
  customer/           Enterprise Entry Agent (:10000) — receives user requests
  orchestrator/       OrchestratorAgent (:10002) — delegates to BusinessTravelAgent
  business_travel/    BusinessTravelAgent (:10004) — coordinates the workflow
  rail/               RailProviderAgent (:10010)
  flight/             FlightProviderAgent (:10011)
  mobility/           MobilityProviderAgent (:10012)

mcp_servers/          Rail / Flight / Mobility MCP servers (:8004 / :8005 / :8006)
                      Mock travel data providers

contracts/
  BusinessTravelPolicy.sol    On-chain policy — selectPolicyCompliantOffer
  BusinessTravelBooking.sol   On-chain booking — createVerifiedBooking
  BusinessAgentRegistry.sol   On-chain registry — capability -> agentId + URI

utilities/
  smart_contract/smart_contract_client.py   Web3 eth_call to BusinessTravelPolicy
  blockchain/business_travel_booking_client.py   Sepolia createVerifiedBooking tx

app/cmd/cmd.py        Enterprise Agent Console CLI

ops/
  deploy/             Hardhat deployment scripts
  registry/           Registry management and diagnostics
  booking/            Booking operations (legacy check_and_complete path)
  demo/               Demo startup and health check scripts
  deployments/        sepolia.json — contract addresses

test/
  business_travel/unit/         Unit tests (no blockchain required)
  business_travel/integration/  Integration tests (Registry, BTA, full chain)
  providers/                    Provider agent tests
  contracts/                    Hardhat contract tests (36 tests)
```

---

## Setup

**Prerequisites:**

- Python 3.13+ with `uv` (`pip install uv`)
- Node.js for Hardhat contract tests

**Install Python dependencies:**

```powershell
uv sync
```

**Configure `.env` in the project root:**

```env
OPENAI_API_KEY=your_openai_key
ALCHEMY_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/your_key
WALLET_PRIVATE_KEY=your_hex_private_key
WALLET_ADDRESS=0xYourAddress
```

`ALCHEMY_RPC_URL`, `WALLET_PRIVATE_KEY`, and `WALLET_ADDRESS` are required for Sepolia interactions (SmartContractClient policy calls and booking transactions). They are not needed for unit tests or provider agent tests.

---

## Start Demo

### Automated start (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython
```

Starts all 9 services in the correct order (MCP servers first, then provider agents, then BusinessTravelAgent, then OrchestratorAgent, then CustomerAgent). Waits for each service to confirm readiness before proceeding.

On slow machines or after a long pause:

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/start_business_travel_demo.ps1 -StopExistingPython -SlowStartup
```

### Health check

```powershell
powershell -ExecutionPolicy Bypass -File ops/demo/check_business_travel_demo.ps1
```

### CLI

```powershell
uv run python app/cmd/cmd.py --agent http://localhost:10000
```

---

## Demo Scenarios

**Scenario A: Rail preferred**

```text
Ich muss Montag um 10 Uhr von Dortmund nach München.
```

Expected: BusinessTravelPolicy selects `rail-1`. Flight/Mobility enrichment is skipped.

**Scenario B: Rail too long, flight selected**

```text
Ich muss Montag um 10 Uhr von Dortmund nach Wien.
```

Expected: No valid rail under 8 hours. FlightProviderAgent + MobilityProviderAgent are called. BusinessTravelPolicy selects `flight-1-with-transfers` (composed from FlightProviderAgent and MobilityProviderAgent).

**Scenario C: A2A Multi-Turn (missing origin)**

```text
Turn 1: Ich muss Montag um 10 Uhr in München sein.
Turn 2: Dortmund
```

Expected: Agent asks for missing origin after Turn 1. Dortmund is accepted in Turn 2. Planning runs for Dortmund -> München.

---

## Verification

```powershell
# Unit tests (no blockchain access required, 13 tests)
uv run python test/business_travel/unit/verify_business_travel_unit.py

# Integration: Registry discovery + BTA internals (requires ALCHEMY_RPC_URL)
uv run python test/business_travel/integration/verify_business_travel.py

# Integration: Full chain Customer -> Orchestrator -> BTA (requires running agents)
uv run python test/business_travel/integration/verify_customer_orchestrator_business_travel.py

# Hardhat contract tests (36 tests, no Sepolia required)
npx hardhat test
```

---

## Stack

- **A2A SDK** (`a2a-sdk`) — Agent-to-Agent JSON-RPC over HTTP
- **MCP SDK** (`mcp`) — Model Context Protocol tool servers
- **OpenAI** (`openai`) — LLM for language understanding and response formatting
- **Web3.py** (`web3`) — Sepolia `eth_call` and transaction signing
- **Starlette / Uvicorn** — A2A server infrastructure
- **Hardhat** — Solidity contract tests

No LangChain. No Google ADK.
