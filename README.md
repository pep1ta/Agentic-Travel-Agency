# Smart-Contract-governed Business Travel Planning

This repository contains a small didactic prototype for controlled agent autonomy in business travel planning.

Example user request:

```text
Ich muss Montag um 10 Uhr von Dortmund nach München.
```

The system collects travel options, structures them, and delegates the final policy-compliant selection to a simulated smart contract client. The important point is that the final travel decision is not made by an LLM and not by an agent.

Detailed architecture documentation: `docs/architecture.md`

## Goal

The prototype demonstrates a business travel workflow in which agents have limited autonomy:

- Agents coordinate the workflow.
- Agents fetch and structure information.
- MCP servers provide mock travel data.
- The LLM may help understand language and explain results.
- The final rule-based selection is performed by `SmartContractClient`.
- Booking and payment are not executed. They are only marked as requiring approval.

In version 1, `SmartContractClient` is a Python mock. It simulates where a real smart contract policy could later sit.

In version 2, the same policy is also implemented as a Solidity contract in `contracts/BusinessTravelPolicy.sol`. The Python prototype still uses the `SmartContractClient` mock. There is no Python-Web3 integration, no testnet deployment, and no real payment flow.

## Architecture Idea

Agent != LLM.

The system flow is:

```text
User
  -> CustomerAgent
  -> OrchestratorAgent
  -> BusinessTravelAgent
  -> Rail MCP Server
  -> Flight MCP Server
  -> Mobility MCP Server
  -> SmartContractClient
  -> Policy-compliant result
```

Roles:

- `CustomerAgent` receives the user's request and forwards it into the A2A system.
- `OrchestratorAgent` delegates business travel requests to the BusinessTravelAgent.
- `BusinessTravelAgent` coordinates the business travel planning workflow.
- MCP servers return mock rail, flight, and mobility data.
- `SmartContractClient` simulates the business travel policy and makes the final selection.

The BusinessTravelAgent may optimize information gathering. For example, if a valid rail option under 8 hours already exists, flight and transfer enrichment can be skipped because rail is preferred by policy. This is not the final offer selection. The final selection still happens in `SmartContractClient`.

## Policy Rules

Version 1 uses a simple business travel policy:

- Rail is preferred if at least one valid rail option with `duration_minutes <= 480` exists.
- 480 minutes equals 8 hours.
- Flight may only win if no valid rail option under 8 hours exists.
- Rail must be second class.
- Flight must be economy.
- Flight must include transfers to and from the airport.
- Total price must be within the policy budget.
- Provider reputation must meet the minimum reputation threshold.
- If multiple offers are valid inside the allowed category, `cheapest_valid` wins.
- Booking and payment require approval.

## Why This Scenario Matters

Business travel is a useful demo scenario because companies often have clear travel policies:

- prefer rail under a certain duration,
- require economy class for flights,
- enforce budget limits,
- require approved providers,
- require approval before booking or payment.

The SmartContractClient acts as the safety anchor. Agents remain useful and autonomous for coordination and information gathering, but the legally or organizationally relevant decision is constrained by deterministic policy logic.

## Project Structure

Important folders and files:

```text
agents/customer/
```

Customer-facing A2A agent. It receives user messages and forwards them to the OrchestratorAgent.

```text
agents/orchestrator/
```

Delegates requests to available sub-agents. For the business travel use case, it delegates to the BusinessTravelAgent.

```text
agents/business_travel/
```

Coordinates the business travel workflow. It calls the rail, flight, and mobility MCP servers, structures offers, and sends them to the SmartContractClient.

```text
mcp_servers/rail_server.py
mcp_servers/flight_server.py
mcp_servers/mobility_server.py
```

Simple MCP servers with mock travel data. They only provide information and do not make the final decision.

```text
utilities/smart_contract/smart_contract_client.py
```

Policy mock for version 1. This is where the final policy-compliant offer is selected.

```text
contracts/BusinessTravelPolicy.sol
```

Solidity version of the same business-travel policy. It is tested locally with Hardhat, but it is not yet connected to the Python agent flow.

```text
utilities/a2a/
```

A2A configuration, especially the sub-agent registry used by the OrchestratorAgent.

```text
utilities/mcp/
```

MCP discovery and connector helpers. For the current business travel smoke test, the Orchestrator does not need old tourist MCP tools.

## Stack

- **A2A SDK** (`a2a-sdk`) for Agent-to-Agent communication.
- **MCP SDK** (`mcp`) for tool servers.
- **OpenAI** (`openai`) for the Orchestrator's language/tool decision loop.
- **Starlette / Uvicorn** for A2A server infrastructure.
- **httpx** for HTTP communication.
- **Hardhat** for local Solidity contract tests.

No LangChain and no Google ADK are used.

## Setup

Install dependencies:

```powershell
uv sync
```

Create a `.env` file with an OpenAI API key:

```powershell
OPENAI_API_KEY=your_key_here
```

## Full Smoke Test

Start each component in a separate terminal, in this order:

```powershell
uv run python mcp_servers/rail_server.py
```

```powershell
uv run python mcp_servers/flight_server.py
```

```powershell
uv run python mcp_servers/mobility_server.py
```

```powershell
uv run python -m agents.business_travel
```

```powershell
uv run python -m agents.orchestrator
```

```powershell
uv run python -m agents.customer
```

```powershell
uv run python app/cmd/cmd.py --agent http://localhost:10000
```

Then enter:

```text
Ich muss Montag um 10 Uhr von Dortmund nach München.
```

## Start Demo With PowerShell Script

On Windows, the demo services can also be started with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_business_travel_demo.ps1
```

The script opens separate PowerShell windows for the MCP servers and agents. It then prints the CLI command to start the user-facing chat.

## Expected Result

The expected policy result is:

- `rail-1` is selected.
- Reason: a valid rail option under 8 hours exists.
- Flight/Mobility enrichment is normally skipped because rail is preferred by policy.
- The final selection is made by `SmartContractClient`.
- No booking or payment is executed.
- Approval is required before booking/payment.

The response should make clear that the agent did not independently choose the best offer. It gathered and structured information, while the SmartContractClient applied the policy.

## Manual Demo Scenarios

**Scenario A: Dortmund -> München**

```text
Ich muss Montag um 10 Uhr von Dortmund nach München.
```

Expected:

- selected_offer_id: `rail-1`
- rail is preferred
- Flight/Mobility is not included unnecessarily

**Scenario B: Dortmund -> Wien**

```text
Ich muss Montag um 10 Uhr von Dortmund nach Wien.
```

Expected:

- selected_offer_id: `flight-1-with-transfers`
- Rail MCP provides no valid rail option under 8 hours
- Flight + Mobility are included

**Scenario C: A2A Multi-Turn Slot Filling**

Turn 1:

```text
Ich muss Montag um 10 Uhr in München sein.
```

The agent asks for the missing origin.

Turn 2:

```text
Münster
```

Expected:

- the A2A context remains open between turns
- destination München and appointment time from Turn 1 are reused
- Münster is interpreted as the missing origin
- planning runs for Münster -> München

A2A Multi-Turn is used only to complete missing request data. The final policy decision is still made by `SmartContractClient`, not by the LLM or the agent.

## Isolated BusinessTravelAgent Demo

For debugging the BusinessTravelAgent without the Orchestrator, run:

```powershell
uv run python -m agents.business_travel.demo
```

This starts the needed mock MCP servers if they are not already running, calls the BusinessTravelAgent directly, and prints the policy result.

The demo shows two scenarios:

**Scenario A: Rail preferred**

- The demo request is: `Ich muss Montag um 10 Uhr von Dortmund nach München.`
- A valid rail option with `duration_minutes <= 480` exists.
- Flight/Mobility enrichment is skipped.
- The SmartContractClient selects `rail-1`.

**Scenario B: Rail too long**

- The demo request is: `Ich muss Montag um 10 Uhr von Dortmund nach Wien.`
- The Rail MCP Server returns no valid Dortmund -> Wien rail option under 8 hours.
- The BusinessTravelAgent calls the Flight MCP Server and the Mobility MCP Server.
- The first economy flight option is combined with airport transfers.
- This creates `flight-1-with-transfers`.
- The SmartContractClient selects `flight-1-with-transfers` if it is policy-compliant.

Scenario B is important because it shows policy-dependent multi-agent/tool coordination. The agent fetches additional information only when the policy makes it necessary. The final selection still remains with the SmartContractClient.

## Automated Verification

Run this command to verify both business travel scenarios:

```powershell
uv run python scripts/verify_business_travel.py
```

The script checks:

- Scenario A: Dortmund -> München has a valid rail option under 8 hours, so the SmartContractClient selects `rail-1`.
- Scenario B: Dortmund -> Wien has no valid rail option under 8 hours, so Flight + Mobility are included and the SmartContractClient selects `flight-1-with-transfers`.
- Scenario C: a missing origin is collected through A2A Multi-Turn slot filling.

Expected output:

```text
Scenario A selected_offer_id: rail-1
Scenario B selected_offer_id: flight-1-with-transfers
Multi-turn selected_offer_id: rail-muenster-1
Business travel verification passed.
```

## Solidity Policy Tests

Version 2 adds a local Solidity version of the business travel policy:

```text
contracts/BusinessTravelPolicy.sol
```

Run the Hardhat tests with:

```powershell
npx hardhat test
```

Expected result:

```text
6 passing
```

The tests cover:

- Rail under 8h wins over flight.
- Long rail allows flight.
- First class rail is invalid.
- Flight without transfers is invalid.
- Provider reputation below 70 is invalid.
- No valid offer returns `NO_SELECTION`.

The Solidity contract mirrors the Python `SmartContractClient` policy logic, but the Python prototype still uses the Python mock. There is no Python-Web3 integration and no testnet deployment.

## Version 1 Does Not Include

Version 1 intentionally avoids advanced infrastructure:

- no real blockchain,
- no ERC-8004,
- no 8004scan,
- no ERC-8183,
- no real payment,
- no real travel APIs,
- no complex memory,
- no generic agent base classes.

The prototype stays small on purpose so the architecture and responsibility boundaries remain easy to inspect in a master thesis demo.
