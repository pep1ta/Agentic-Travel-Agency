"""Blockchain adapter for BusinessTravelPolicy Smart Contract on Sepolia.

This client calls the deployed BusinessTravelPolicy contract via Web3.
It is NOT a policy engine — all policy decisions happen in Solidity.

Responsibilities of this client:
  - Load contract ABI and address from deployments/sepolia.json
  - Convert Python offer dicts to Solidity TravelOffer tuples
  - Call selectPolicyCompliantOffer() and per-offer validation functions via eth_call
  - Decode the contract result into a structured Python dict

What this client must NOT do:
  - Implement any policy rules in Python
  - Fall back to a local policy mock if the contract is unreachable
  - Invent rejection reasons not provided by the contract

Contract on Sepolia: BusinessTravelPolicy.sol
Deployed at: see deployments/sepolia.json → contracts.businessTravelPolicy.address

For unit tests without ALCHEMY_RPC_URL or Sepolia access:
  use test/mocks/mock_smart_contract_client.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CHAIN_ID = 11155111
DEPLOYMENT_FILE = Path("ops/deployments/sepolia.json")
ARTIFACT_FILE = Path(
    "build/hardhat/artifacts/contracts/BusinessTravelPolicy.sol/BusinessTravelPolicy.json"
)

# type(uint256).max — returned by contract when no offer qualifies
_NO_SELECTION = 2**256 - 1

# Encoding maps for BusinessTravelPolicy.sol constants:
# MODE_RAIL=0, MODE_FLIGHT_WITH_TRANSFERS=1
_MODE_ENCODING: dict[str, int] = {
    "rail": 0,
    "flight_with_transfers": 1,
}
# CLASS_SECOND=0, CLASS_FIRST=1, CLASS_ECONOMY=2, CLASS_BUSINESS=3
_CLASS_ENCODING: dict[str, int] = {
    "second_class": 0,
    "first_class": 1,
    "economy": 2,
    "business": 3,
}


class SmartContractClientError(RuntimeError):
    """Raised when the policy contract cannot be configured or reached."""


def _load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SmartContractClientError(
            f"BusinessTravelPolicy contract call failed: {name} ist nicht gesetzt. "
            "Für Unit-Tests ohne Blockchain: MockSmartContractClient verwenden "
            "(test/mocks/mock_smart_contract_client.py)."
        )
    return value


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise SmartContractClientError(
            f"BusinessTravelPolicy contract call failed: {path} nicht gefunden."
        )
    return json.loads(path.read_text(encoding="utf-8"))


class SmartContractClient:
    """Blockchain adapter for BusinessTravelPolicy.sol on Sepolia.

    All policy decisions are made by the Solidity contract.
    This class only translates between Python dicts and Solidity ABI types.
    """

    def __init__(self) -> None:
        self._web3 = None
        self._contract = None
        self._policy_address: str | None = None

    def _ensure_loaded(self) -> None:
        """Lazily initialises the Web3 connection and contract binding.

        Called on first use so BusinessTravelAgent.__init__ can create a
        SmartContractClient without requiring ALCHEMY_RPC_URL at import time.
        The RPC URL is only needed when a contract call is actually made.
        """
        if self._contract is not None:
            return

        try:
            from web3 import Web3
        except ImportError as exc:
            raise SmartContractClientError(
                "BusinessTravelPolicy contract call failed: "
                "Python-Dependency 'web3' fehlt. Run: pip install web3. "
                "Für Unit-Tests: test/mocks/mock_smart_contract_client.py verwenden."
            ) from exc

        _load_local_env()
        rpc_url = _require_env("ALCHEMY_RPC_URL")

        deployment = _read_json(DEPLOYMENT_FILE)
        raw_address = (
            deployment.get("contracts", {})
            .get("businessTravelPolicy", {})
            .get("address")
        )
        if not raw_address:
            raise SmartContractClientError(
                "BusinessTravelPolicy contract call failed: "
                "contracts.businessTravelPolicy.address fehlt in "
                "deployments/sepolia.json."
            )

        artifact = _read_json(ARTIFACT_FILE)

        web3 = Web3(Web3.HTTPProvider(rpc_url))
        if not web3.is_connected():
            raise SmartContractClientError(
                "BusinessTravelPolicy contract call failed: RPC nicht erreichbar."
            )

        chain_id = web3.eth.chain_id
        if chain_id != CHAIN_ID:
            raise SmartContractClientError(
                f"BusinessTravelPolicy contract call failed: "
                f"Falsche Chain ID {chain_id}; erwartet {CHAIN_ID}."
            )

        self._web3 = web3
        self._policy_address = Web3.to_checksum_address(raw_address)
        self._contract = web3.eth.contract(
            address=self._policy_address, abi=artifact["abi"]
        )

    def select_policy_compliant_offer(self, offers: list[dict]) -> dict:
        """Calls BusinessTravelPolicy.selectPolicyCompliantOffer() via eth_call.

        The Solidity function is `pure` — no transaction, no gas cost.
        For each non-selected offer, isValidRailOffer() or isValidFlightOffer()
        is called to distinguish valid alternatives from rejected offers.

        Returns a structured dict with:
          selected_offer, valid_alternatives, rejected_options,
          considered_offers, decision_reason, decision_source,
          contract_address, chain_id, booking_requires_approval.
        """
        self._ensure_loaded()

        encoded_offers = [self._encode_offer(o) for o in offers]

        # pure view call — no gas, no wallet needed
        selected_index: int = self._contract.functions.selectPolicyCompliantOffer(
            encoded_offers
        ).call()

        selected_offer = (
            offers[selected_index] if selected_index != _NO_SELECTION else None
        )

        valid_alternatives: list[dict] = []
        rejected_options: list[dict] = []

        for i, offer in enumerate(offers):
            if i == selected_index:
                continue
            if self._is_valid(offer):
                valid_alternatives.append(offer)
            else:
                rejected_options.append({
                    "offer_id": offer.get("offer_id", "(missing)"),
                    # TODO: Extend BusinessTravelPolicy.sol to return reason-code
                    # flags (REASON_OVER_BUDGET, REASON_WRONG_CLASS, etc.) so that
                    # rejection reasons can be read from the contract rather than
                    # described as a placeholder here.
                    "reasons": [
                        f"Rejected by BusinessTravelPolicyContract "
                        f"at {self._policy_address}. "
                        "Detailed reason codes are not yet available in the "
                        "current contract version."
                    ],
                })

        if selected_offer:
            mode = selected_offer.get("mode")
            if mode == "rail":
                decision_reason = (
                    "A policy-compliant rail offer under 8 hours exists. "
                    "Rail is preferred. Cheapest valid rail selected by contract."
                )
            else:
                decision_reason = (
                    "No policy-compliant rail offer under 8 hours found. "
                    "Cheapest valid flight-with-transfers selected by contract."
                )
        else:
            decision_reason = "No policy-compliant travel offer found by contract."

        return {
            "selected_offer": selected_offer,
            "valid_alternatives": valid_alternatives,
            "rejected_options": rejected_options,
            "rejected_offers": rejected_options,  # backwards-compat alias
            "considered_offers": list(offers),
            "decision_reason": decision_reason,
            "booking_requires_approval": True,
            "decision_source": "BusinessTravelPolicyContract",
            "contract_address": self._policy_address,
            "chain_id": CHAIN_ID,
        }

    def _is_valid(self, offer: dict) -> bool:
        """Calls isValidRailOffer() or isValidFlightOffer() per offer via eth_call."""
        encoded = self._encode_offer(offer)
        mode = offer.get("mode")
        if mode == "rail":
            return bool(self._contract.functions.isValidRailOffer(encoded).call())
        if mode == "flight_with_transfers":
            return bool(self._contract.functions.isValidFlightOffer(encoded).call())
        return False

    @staticmethod
    def _encode_offer(offer: dict) -> tuple:
        """Converts a Python offer dict to a Solidity TravelOffer tuple.

        Field order matches the TravelOffer struct in BusinessTravelPolicy.sol:
          (offerId, mode, totalPrice, durationMinutes, travelClass,
           providerReputation, arrivalBufferMinutes, transfersIncluded)
        """
        def _require(field: str):
            value = offer.get(field)
            if value is None:
                raise SmartContractClientError(
                    f"Offer is missing required field '{field}' "
                    f"(offer_id={offer.get('offer_id', '(missing)')!r})."
                )
            return value

        offer_id = _require("offer_id")
        if not str(offer_id).strip():
            raise SmartContractClientError("Offer field 'offer_id' must not be empty.")

        mode = str(_require("mode"))
        if mode not in _MODE_ENCODING:
            raise SmartContractClientError(
                f"Unknown offer mode {mode!r}. "
                f"Supported: {list(_MODE_ENCODING)}."
            )

        travel_class = str(_require("travel_class"))
        if travel_class not in _CLASS_ENCODING:
            raise SmartContractClientError(
                f"Unknown travel_class {travel_class!r}. "
                f"Supported: {list(_CLASS_ENCODING)}."
            )

        total_price = _require("total_price")
        duration_minutes = _require("duration_minutes")
        provider_reputation = _require("provider_reputation")
        arrival_buffer_minutes = _require("arrival_buffer_minutes")

        if mode == "flight_with_transfers" and offer.get("transfers_included") is None:
            raise SmartContractClientError(
                f"Flight offer {offer_id!r} is missing required field 'transfers_included'."
            )

        return (
            str(offer_id),
            _MODE_ENCODING[mode],
            int(total_price),
            int(duration_minutes),
            _CLASS_ENCODING[travel_class],
            int(provider_reputation),
            int(arrival_buffer_minutes),
            bool(offer.get("transfers_included", False)),
        )
