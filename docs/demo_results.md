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
