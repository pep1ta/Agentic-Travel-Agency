# Business Travel Demo Results

This document summarizes the two verified business-travel demo scenarios.

## Scenario A: Rail Preferred

- A valid rail option under 8 hours exists.
- Flight/Mobility enrichment is skipped.
- `SmartContractClient` selects `rail-1`.
- No booking or payment is executed.
- Approval is required.

## Scenario B: Rail Too Long

- Rail is treated as over 8 hours in the demo context.
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
