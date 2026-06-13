"""Policy mock for smart-contract-governed business travel planning.

This module intentionally uses plain dictionaries. The goal for version 1 is
to make the policy rules easy to read before replacing this mock with a real
Solidity smart contract later.
"""


class SmartContractClient:
    """Simulates a smart contract that selects a policy-compliant travel offer.

    Version 1 does not connect to a blockchain. It only simulates the behavior
    of a smart contract locally in Python.

    Important separation of responsibilities:
    - Agents later collect and structure travel information.
    - The LLM may understand language and explain results.
    - The final policy-based selection happens here.

    In a later version, this class could be replaced by a client that calls a
    real Solidity smart contract with the same policy responsibilities.
    """

    def __init__(self):
        self._policy = {
            "name": "Business Travel Policy V1",
            "rail_preferred_max_duration_minutes": 480,
            "max_budget": 500,
            "min_provider_reputation": 70,
            "min_arrival_buffer_minutes": 30,
            "booking_requires_approval": True,
            "selection_rule": "cheapest_valid",
        }

    def get_policy(self) -> dict:
        """Returns the active business travel policy as a plain dictionary."""
        return self._policy.copy()

    def select_policy_compliant_offer(self, offers: list[dict]) -> dict:
        """Checks all offers against the policy and selects the winning offer.

        Rail is preferred when at least one valid rail offer exists with a
        duration of 480 minutes or less. In that case, flight offers are still
        evaluated for transparency, but they cannot win.
        """
        valid_rail_offers = []
        valid_flight_offers = []
        rejected_offers = []
        considered_offers = list(offers)

        for offer in offers:
            if offer.get("mode") == "rail":
                reasons = self._rail_rejection_reasons(offer)
                if reasons:
                    rejected_offers.append(self._rejection(offer, reasons))
                else:
                    valid_rail_offers.append(offer)
            elif offer.get("mode") == "flight_with_transfers":
                reasons = self._flight_rejection_reasons(offer)
                if reasons:
                    rejected_offers.append(self._rejection(offer, reasons))
                else:
                    valid_flight_offers.append(offer)
            else:
                rejected_offers.append(self._rejection(
                    offer,
                    [f"Unsupported travel mode: {offer.get('mode')}."],
                ))

        valid_preferred_rail = [
            offer
            for offer in valid_rail_offers
            if offer.get("duration_minutes", 0) <= self._policy["rail_preferred_max_duration_minutes"]
        ]

        if valid_preferred_rail:
            selected_offer = self._cheapest(valid_preferred_rail)
            valid_offers = valid_rail_offers + valid_flight_offers
            valid_alternatives = self._valid_alternatives(valid_offers, selected_offer)
            return {
                "selected_offer": selected_offer,
                "valid_offers": valid_preferred_rail,
                "valid_alternatives": valid_alternatives,
                "rejected_offers": rejected_offers,
                "rejected_options": rejected_offers,
                "considered_offers": considered_offers,
                "decision_reason": (
                    "A policy-compliant rail offer under 8 hours exists. "
                    "Rail is preferred, so the cheapest valid rail offer wins."
                ),
                "booking_requires_approval": self._policy["booking_requires_approval"],
            }

        if valid_flight_offers:
            selected_offer = self._cheapest(valid_flight_offers)
            valid_offers = valid_rail_offers + valid_flight_offers
            valid_alternatives = self._valid_alternatives(valid_offers, selected_offer)
            return {
                "selected_offer": selected_offer,
                "valid_offers": valid_flight_offers,
                "valid_alternatives": valid_alternatives,
                "rejected_offers": rejected_offers,
                "rejected_options": rejected_offers,
                "considered_offers": considered_offers,
                "decision_reason": (
                    "No policy-compliant rail offer under 8 hours exists. "
                    "Flight is allowed, so the cheapest valid flight offer wins."
                ),
                "booking_requires_approval": self._policy["booking_requires_approval"],
            }

        return {
            "selected_offer": None,
            "valid_offers": [],
            "valid_alternatives": [],
            "rejected_offers": rejected_offers,
            "rejected_options": rejected_offers,
            "considered_offers": considered_offers,
            "decision_reason": "No policy-compliant travel offer was found.",
            "booking_requires_approval": self._policy["booking_requires_approval"],
        }

    def _rail_rejection_reasons(self, offer: dict) -> list[str]:
        """Returns all policy reasons why a rail offer is invalid."""
        reasons = []

        if offer.get("mode") != "rail":
            reasons.append("Rail offer must have mode == 'rail'.")
        if offer.get("travel_class") != "second_class":
            reasons.append("Rail offer must be second class.")
        if offer.get("total_price", 0) > self._policy["max_budget"]:
            reasons.append("Rail offer exceeds the maximum budget.")
        if offer.get("provider_reputation", 0) < self._policy["min_provider_reputation"]:
            reasons.append("Rail provider reputation is too low.")
        if offer.get("arrival_buffer_minutes", 0) < self._policy["min_arrival_buffer_minutes"]:
            reasons.append("Rail arrival buffer is too short.")

        return reasons

    def _flight_rejection_reasons(self, offer: dict) -> list[str]:
        """Returns all policy reasons why a flight offer is invalid."""
        reasons = []

        if offer.get("mode") != "flight_with_transfers":
            reasons.append("Flight offer must have mode == 'flight_with_transfers'.")
        if offer.get("travel_class") != "economy":
            reasons.append("Flight offer must be economy class.")
        if offer.get("transfers_included") is not True:
            reasons.append("Flight offer must include transfers to and from the airport.")
        if offer.get("total_price", 0) > self._policy["max_budget"]:
            reasons.append("Flight offer exceeds the maximum budget.")
        if offer.get("provider_reputation", 0) < self._policy["min_provider_reputation"]:
            reasons.append("Flight provider reputation is too low.")
        if offer.get("arrival_buffer_minutes", 0) < self._policy["min_arrival_buffer_minutes"]:
            reasons.append("Flight arrival buffer is too short.")

        return reasons

    def _cheapest(self, offers: list[dict]) -> dict:
        """Returns the cheapest offer. offer_id breaks ties deterministically."""
        return min(offers, key=lambda offer: (offer.get("total_price", 0), offer.get("offer_id", "")))

    def _valid_alternatives(self, valid_offers: list[dict], selected_offer: dict) -> list[dict]:
        """Returns valid but non-selected offers with a simple explanation."""
        selected_offer_id = selected_offer.get("offer_id")
        alternatives = []

        for offer in valid_offers:
            if offer.get("offer_id") == selected_offer_id:
                continue

            alternative = offer.copy()
            alternative["not_selected_reasons"] = [
                self._alternative_reason(offer, selected_offer)
            ]
            alternatives.append(alternative)

        return alternatives

    def _alternative_reason(self, offer: dict, selected_offer: dict) -> str:
        """Explains why a valid offer did not win."""
        selected_mode = selected_offer.get("mode")

        if offer.get("mode") == "rail" and offer.get("duration_minutes", 0) > self._policy["rail_preferred_max_duration_minutes"]:
            return "Rail is valid but not under the 8-hour rail preference threshold."

        if offer.get("total_price", 0) > selected_offer.get("total_price", 0):
            if selected_mode == "rail":
                return "More expensive than the selected valid rail offer."
            if selected_mode == "flight_with_transfers":
                return "More expensive than the selected valid flight offer."
            return "More expensive than the selected valid offer."

        if selected_mode == "rail" and offer.get("mode") == "flight_with_transfers":
            return "Rail is preferred because a valid rail option under 8 hours exists."

        return "Not the cheapest valid offer in the allowed policy category."

    def _rejection(self, offer: dict, reasons: list[str]) -> dict:
        """Builds a small rejection record for transparent policy explanations."""
        return {
            "offer_id": offer.get("offer_id", "(missing offer_id)"),
            "reasons": reasons,
        }


if __name__ == "__main__":
    client = SmartContractClient()

    example_offers = [
        {
            "offer_id": "rail-1",
            "mode": "rail",
            "provider": "RailProviderAgent",
            "total_price": 119,
            "duration_minutes": 395,
            "travel_class": "second_class",
            "provider_reputation": 82,
            "arrival_buffer_minutes": 75,
            "transfers_included": True,
        },
        {
            "offer_id": "flight-1",
            "mode": "flight_with_transfers",
            "provider": "FlightProviderAgent",
            "total_price": 99,
            "duration_minutes": 210,
            "travel_class": "economy",
            "provider_reputation": 86,
            "arrival_buffer_minutes": 60,
            "transfers_included": True,
        },
        {
            "offer_id": "rail-2",
            "mode": "rail",
            "provider": "RailProviderAgent",
            "total_price": 89,
            "duration_minutes": 420,
            "travel_class": "first_class",
            "provider_reputation": 90,
            "arrival_buffer_minutes": 45,
            "transfers_included": True,
        },
    ]

    decision = client.select_policy_compliant_offer(example_offers)
    selected_offer = decision["selected_offer"]

    if selected_offer:
        print(f"Selected offer: {selected_offer['offer_id']}")
    else:
        print("Selected offer: none")

    print(f"Decision reason: {decision['decision_reason']}")
    print(f"Booking requires approval: {decision['booking_requires_approval']}")
