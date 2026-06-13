# Business Travel Demo Results

This document summarizes the two verified business-travel demo scenarios.

## Scenario A: Rail Preferred

- Request: `Ich muss Montag um 10 Uhr von Dortmund nach München.`
- A valid rail option under 8 hours exists.
- Flight/Mobility enrichment is skipped.
- `SmartContractClient` selects `rail-1`.
- No booking or payment is executed.
- Approval is required.

## Scenario B: Rail Too Long

- Request: `Ich muss Montag um 10 Uhr von Dortmund nach Wien.`
- The Rail MCP Server returns no valid Dortmund -> Wien rail option under 8 hours.
- Flight + Mobility are included.
- `flight-1-with-transfers` is built.
- `SmartContractClient` selects `flight-1-with-transfers`.
- No booking or payment is executed.
- Approval is required.

## What This Shows

- Agents collect and coordinate information.
- `SmartContractClient` makes the rule-based selection.
- The policy controls whether additional tools are included.
- Agent autonomy is limited by a predefined action and policy framework.

## Scenario C: A2A Multi-Turn Slot Filling

Turn 1:

```text
Ich muss Montag um 10 Uhr in München sein.
```

The agent asks for the missing origin.

Turn 2:

```text
Münster
```

Expected result:

- The A2A context remains open between turns.
- Destination München and the appointment time from Turn 1 are reused.
- Münster is interpreted as the missing origin.
- Travel planning runs for Münster -> München.
- The final policy selection is still made by `SmartContractClient`.

Multi-turn only completes missing request data. It does not move the policy decision into the LLM or the agent.

## Verification Commands

```text
uv run python scripts/verify_business_travel.py
npx hardhat test
```

## V2 Solidity Policy Check

Version 2 adds `contracts/BusinessTravelPolicy.sol`, a Solidity contract that mirrors the same business-travel policy currently simulated by the Python `SmartContractClient`.

The contract is tested locally with Hardhat:

```text
npx hardhat test
```

Expected result:

```text
6 passing
```

Covered policy cases:

- Rail under 8h wins over flight.
- Long rail allows flight.
- First class rail is invalid.
- Flight without transfers is invalid.
- Provider reputation below 70 is invalid.
- No valid offer returns `NO_SELECTION`.

The Python prototype still uses the `SmartContractClient` mock. There is no Python-Web3 integration and no testnet deployment.
