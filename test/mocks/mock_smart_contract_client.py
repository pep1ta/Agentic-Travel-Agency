"""Local policy mock for unit tests that run without ALCHEMY_RPC_URL or Sepolia access.

This module replaces SmartContractClient in unit-test scenarios where no blockchain
connection is available or desirable. It re-implements the same policy rules that
are encoded in BusinessTravelPolicy.sol so that unit tests remain deterministic.

IMPORTANT:
  - This mock is ONLY for test/business_travel/unit/verify_business_travel_unit.py.
  - It must NOT be imported by agents/business_travel/agent.py or any production code.
  - It must NOT be used in test/business_travel/integration/verify_business_travel.py.
  - The real SmartContractClient in utilities/smart_contract/smart_contract_client.py
    must be used in production.

Policy rules here mirror BusinessTravelPolicy.sol exactly.
If the Solidity contract is updated, this mock must be updated in sync.
"""

from __future__ import annotations


class MockSmartContractClient:
    """Local Python re-implementation of BusinessTravelPolicy.sol for unit tests only.

    Mirrors the policy logic in BusinessTravelPolicy.sol:
      - MAX_BUDGET = 450
      - MIN_PROVIDER_REPUTATION = 70
      - MIN_ARRIVAL_BUFFER_MINUTES = 30
      - RAIL_PREFERRED_UNTIL_MINUTES = 480
      - Rail is preferred over flight when a valid rail offer under 8 hours exists.
      - Cheapest valid offer wins within each category.
    """

    _POLICY = {
        "rail_preferred_max_duration_minutes": 480,
        "max_budget": 450,
        "min_provider_reputation": 70,
        "min_arrival_buffer_minutes": 30,
        "booking_requires_approval": True,
    }

    def select_policy_compliant_offer(self, offers: list[dict]) -> dict:
        """Mirrors BusinessTravelPolicy.selectPolicyCompliantOffer() in Python."""
        valid_rail: list[dict] = []
        valid_flight: list[dict] = []
        rejected: list[dict] = []
        considered = list(offers)

        for offer in offers:
            mode = offer.get("mode")
            if mode == "rail":
                reasons = self._rail_rejection_reasons(offer)
                if reasons:
                    rejected.append({"offer_id": offer.get("offer_id"), "reasons": reasons})
                else:
                    valid_rail.append(offer)
            elif mode == "flight_with_transfers":
                reasons = self._flight_rejection_reasons(offer)
                if reasons:
                    rejected.append({"offer_id": offer.get("offer_id"), "reasons": reasons})
                else:
                    valid_flight.append(offer)
            else:
                rejected.append({
                    "offer_id": offer.get("offer_id"),
                    "reasons": [f"Unsupported travel mode: {mode}."],
                })

        preferred_rail = [
            o for o in valid_rail
            if o.get("duration_minutes", 0) <= self._POLICY["rail_preferred_max_duration_minutes"]
        ]

        if preferred_rail:
            selected = self._cheapest(preferred_rail)
            selected_index = considered.index(selected)
            all_valid = valid_rail + valid_flight
            alternatives = self._alternatives(all_valid, selected)
            return {
                "selected_offer": selected,
                "selected_index": selected_index,
                "valid_alternatives": alternatives,
                "rejected_options": rejected,
                "rejected_offers": rejected,
                "considered_offers": considered,
                "decision_reason": (
                    "A policy-compliant rail offer under 8 hours exists. "
                    "Rail is preferred. Cheapest valid rail selected."
                ),
                "booking_requires_approval": self._POLICY["booking_requires_approval"],
                "decision_source": "MockSmartContractClient (unit test only)",
            }

        if valid_flight:
            selected = self._cheapest(valid_flight)
            selected_index = considered.index(selected)
            all_valid = valid_rail + valid_flight
            alternatives = self._alternatives(all_valid, selected)
            return {
                "selected_offer": selected,
                "selected_index": selected_index,
                "valid_alternatives": alternatives,
                "rejected_options": rejected,
                "rejected_offers": rejected,
                "considered_offers": considered,
                "decision_reason": (
                    "No policy-compliant rail offer under 8 hours. "
                    "Cheapest valid flight-with-transfers selected."
                ),
                "booking_requires_approval": self._POLICY["booking_requires_approval"],
                "decision_source": "MockSmartContractClient (unit test only)",
            }

        return {
            "selected_offer": None,
            "selected_index": None,
            "valid_alternatives": [],
            "rejected_options": rejected,
            "rejected_offers": rejected,
            "considered_offers": considered,
            "decision_reason": "No policy-compliant travel offer found.",
            "booking_requires_approval": self._POLICY["booking_requires_approval"],
            "decision_source": "MockSmartContractClient (unit test only)",
        }

    def _rail_rejection_reasons(self, offer: dict) -> list[str]:
        reasons = []
        if offer.get("travel_class") != "second_class":
            reasons.append("Rail offer must be second class.")
        if offer.get("total_price", 0) > self._POLICY["max_budget"]:
            reasons.append("Rail offer exceeds the maximum budget.")
        if offer.get("provider_reputation", 0) < self._POLICY["min_provider_reputation"]:
            reasons.append("Rail provider reputation is too low.")
        if offer.get("arrival_buffer_minutes", 0) < self._POLICY["min_arrival_buffer_minutes"]:
            reasons.append("Rail arrival buffer is too short.")
        return reasons

    def _flight_rejection_reasons(self, offer: dict) -> list[str]:
        reasons = []
        if offer.get("travel_class") != "economy":
            reasons.append("Flight offer must be economy class.")
        if offer.get("transfers_included") is not True:
            reasons.append("Flight offer must include transfers.")
        if offer.get("total_price", 0) > self._POLICY["max_budget"]:
            reasons.append("Flight offer exceeds the maximum budget.")
        if offer.get("provider_reputation", 0) < self._POLICY["min_provider_reputation"]:
            reasons.append("Flight provider reputation is too low.")
        if offer.get("arrival_buffer_minutes", 0) < self._POLICY["min_arrival_buffer_minutes"]:
            reasons.append("Flight arrival buffer is too short.")
        return reasons

    @staticmethod
    def _cheapest(offers: list[dict]) -> dict:
        return min(offers, key=lambda o: (o.get("total_price", 0), o.get("offer_id", "")))

    @staticmethod
    def _alternatives(valid: list[dict], selected: dict) -> list[dict]:
        sid = selected.get("offer_id")
        return [o for o in valid if o.get("offer_id") != sid]
