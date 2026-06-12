# Business Travel Prototype Architecture

This document describes the architecture of the Smart-Contract-governed Business Travel Planning prototype.

## 1. Goal of the Architecture

The prototype demonstrates controlled agent autonomy in a business travel planning scenario.

The central idea is:

- Agents collect and coordinate information.
- MCP servers provide structured mock data.
- The final rule-based selection is made by `SmartContractClient` in V1 and by a Solidity smart contract model in V2.
- Booking and payment are not executed automatically.

The architecture separates coordination from decision authority. Agents may act autonomously within the workflow, but the final policy-relevant decision is constrained by explicit policy logic.

## 2. Core Principle: Agent != LLM

In this prototype, an agent is not the same thing as an LLM.

An agent is a stateful, goal-oriented system component. It receives a task, coordinates calls to other components, structures information, and returns a result.

The LLM is used only for language-related tasks such as:

- understanding user intent,
- delegating to the right agent,
- explaining results in natural language.

The LLM does not make the final policy decision. The final decision is made by deterministic policy logic in `SmartContractClient` or, in V2, the Solidity `BusinessTravelPolicy` contract.

## 3. Components

### CustomerAgent

The `CustomerAgent` is the user-facing entry point. It receives user messages and forwards them into the A2A system.

### OrchestratorAgent

The `OrchestratorAgent` delegates requests to the appropriate sub-agent. For business travel planning, it delegates to the `BusinessTravelAgent`.

### BusinessTravelAgent

The `BusinessTravelAgent` coordinates the business travel workflow. It extracts simple origin/destination information, calls MCP servers, structures travel offers, and passes the offer bundle to the policy component.

It does not make the final travel selection.

### Rail MCP Server

The Rail MCP Server provides mock rail offers. For example:

- Dortmund -> München includes a valid rail option under 8 hours.
- Dortmund -> Wien does not include a valid rail option under 8 hours.

### Flight MCP Server

The Flight MCP Server provides mock flight offers. These are raw flight offers and do not include airport transfers.

### Mobility MCP Server

The Mobility MCP Server provides mock airport transfer data. The `BusinessTravelAgent` combines this data with a flight offer to build a `flight_with_transfers` offer.

### SmartContractClient

The `SmartContractClient` is the V1 Python mock of a smart contract. It applies the business travel policy and selects the policy-compliant offer.

### Solidity BusinessTravelPolicy Contract

The Solidity contract `contracts/BusinessTravelPolicy.sol` implements the same policy logic as a local smart contract model. It is tested with Hardhat but is not yet integrated into the Python agent runtime.

## 4. Data Flow

The main data flow is:

```text
User Request
  -> CustomerAgent
  -> OrchestratorAgent
  -> BusinessTravelAgent
  -> Rail / Flight / Mobility MCP Servers
  -> Offer Bundle
  -> SmartContractClient
  -> Result with Approval Hint
```

Example:

```text
Ich muss Montag um 10 Uhr von Dortmund nach München.
```

The `BusinessTravelAgent` extracts:

- origin: Dortmund
- destination: München

It then fetches travel options, structures them as dictionaries, and passes them to `SmartContractClient.select_policy_compliant_offer(...)`.

The result contains:

- selected offer,
- rejected offers,
- decision reason,
- `booking_requires_approval = True`.

## 5. Policy-aware Enrichment

The `BusinessTravelAgent` uses policy-aware enrichment to avoid unnecessary tool calls.

If a valid rail option under or equal to 8 hours exists:

- Flight/Mobility enrichment is skipped.
- Rail options are passed to the `SmartContractClient`.
- The agent does not choose the winner itself.

If no valid rail option under or equal to 8 hours exists:

- Flight options are fetched.
- Mobility transfers are fetched.
- The first economy flight is combined with transfer data.
- The combined `flight_with_transfers` offer is passed to the `SmartContractClient`.

This optimization is still not the final decision. It only decides which information must be prepared before policy evaluation.

## 6. On-chain / Off-chain Separation

### Off-chain

The following parts are off-chain in the prototype:

- user request,
- agent coordination,
- MCP tool calls,
- mock travel offers,
- response explanation to the user.

These parts are flexible and interaction-oriented.

### Policy / Smart Contract

The policy layer contains the hard selection rules:

- budget,
- provider reputation,
- travel class,
- rail preference,
- transfer requirement,
- `NO_SELECTION`.

This layer is the decision authority. In V1 it is represented by the Python `SmartContractClient`. In V2 it is also represented by the Solidity `BusinessTravelPolicy` contract.

## 7. V1 and V2

### V1

V1 contains:

- Python `SmartContractClient` mock,
- working A2A/MCP agent prototype,
- mock rail, flight, and mobility data,
- no real blockchain.

V1 is the executable agent demo.

### V2

V2 adds:

- Solidity contract `contracts/BusinessTravelPolicy.sol`,
- local Hardhat tests,
- the same core policy logic as the Python mock.

V2 does not yet include:

- Python-Web3 integration,
- testnet deployment,
- real on-chain payment or booking.

## 8. Verified Scenarios

### Scenario A: Dortmund -> München

- A valid rail option under 8 hours exists.
- Flight/Mobility enrichment is skipped.
- Selected offer: `rail-1`.

### Scenario B: Dortmund -> Wien

- No valid rail option under 8 hours exists.
- Flight + Mobility are included.
- A `flight_with_transfers` offer is built.
- Selected offer: `flight-1-with-transfers`.

Both scenarios are verified by:

```text
uv run python scripts/verify_business_travel.py
```

## 9. Security and Governance Meaning

The smart contract policy layer acts as a safety anchor.

It provides:

- a technically enforceable action framework,
- deterministic policy checks,
- separation between information gathering and final decision-making,
- auditable decision reasons,
- no booking or payment without approval.

This is important for business travel because travel decisions often have organizational, legal, and financial consequences.

## 10. Deliberate Limits

The prototype intentionally does not include:

- real travel APIs,
- real payment,
- real blockchain integration in the Python agent,
- ERC-8004,
- ERC-8183,
- 8004scan,
- full travel optimization,
- production-grade identity, wallet, or settlement infrastructure.

These limits keep the system small enough for a focused master thesis demo while preserving the central architectural idea: agents coordinate, policy decides.
