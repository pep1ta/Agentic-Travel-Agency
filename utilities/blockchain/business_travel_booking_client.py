"""Small Web3 client for BusinessTravelBooking demo transactions.

This client is used only after a user explicitly asks to book a previously
selected business travel offer. It does not book real travel. It creates a
Sepolia Booking-/Payment-Simulation on the deployed BusinessTravelBooking
contract.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CHAIN_ID = 11155111
DEPLOYMENT_FILE = Path("deployments/sepolia.json")
ARTIFACT_FILE = Path(
    "artifacts/contracts/BusinessTravelBooking.sol/BusinessTravelBooking.json"
)


class BookingClientError(Exception):
    """Raised when the Sepolia booking simulation cannot be created."""


def _load_local_env() -> None:
    """Minimal .env loader using the existing project variable names."""
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
    value = os.environ.get(name)

    if not value:
        raise BookingClientError(
            f"Sepolia Booking ist nicht konfiguriert: {name} fehlt."
        )

    return value


def _normalize_private_key(private_key: str) -> str:
    return private_key if private_key.startswith("0x") else f"0x{private_key}"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BookingClientError(f"Sepolia Booking ist nicht konfiguriert: {path} fehlt.")

    return json.loads(path.read_text(encoding="utf-8"))


def _load_contract_data() -> tuple[str, str, list[dict]]:
    deployment = _read_json(DEPLOYMENT_FILE)
    contracts = deployment.get("contracts", {})
    booking_address = contracts.get("businessTravelBooking", {}).get("address")
    policy_address = contracts.get("businessTravelPolicy", {}).get("address")

    if not booking_address:
        raise BookingClientError(
            "Sepolia Booking ist nicht konfiguriert: businessTravelBooking fehlt."
        )

    if not policy_address:
        raise BookingClientError(
            "Sepolia Booking ist nicht konfiguriert: businessTravelPolicy fehlt."
        )

    artifact = _read_json(ARTIFACT_FILE)
    return booking_address, policy_address, artifact["abi"]


def _booking_values_from_offer(selected_offer: dict) -> dict[str, Any]:
    selected_offer_id = selected_offer.get("id") or selected_offer.get("offer_id")
    mode = selected_offer.get("mode")

    if not selected_offer_id:
        raise BookingClientError("Selected offer has no id or offer_id.")

    if mode == "rail":
        provider_agent_id = 2
        amount_eth = "0.0001"
    elif mode == "flight_with_transfers":
        provider_agent_id = 3
        amount_eth = "0.00015"
    else:
        raise BookingClientError(f"Unsupported booking mode: {mode}")

    return {
        "business_travel_agent_id": 1,
        "provider_agent_id": provider_agent_id,
        "selected_offer_id": selected_offer_id,
        "booking_uri": f"local://bookings/business-travel/{selected_offer_id}-demo",
        "amount_eth": amount_eth,
    }


def _build_booking_transaction(selected_offer: dict):
    """Prepare Web3 objects and an unsigned createBooking transaction."""
    try:
        from eth_account import Account
        from web3 import Web3
    except ImportError as exc:
        raise BookingClientError(
            "Sepolia Booking ist nicht konfiguriert: Python dependency web3 fehlt."
        ) from exc

    _load_local_env()

    rpc_url = _require_env("ALCHEMY_RPC_URL")
    private_key = _normalize_private_key(_require_env("WALLET_PRIVATE_KEY"))
    expected_wallet_address = os.environ.get("WALLET_ADDRESS")

    account = Account.from_key(private_key)

    if (
        expected_wallet_address
        and account.address.lower() != expected_wallet_address.lower()
    ):
        raise BookingClientError(
            "Sepolia Booking ist nicht konfiguriert: WALLET_ADDRESS passt nicht zum Private Key."
        )

    booking_address, policy_address, abi = _load_contract_data()
    booking_values = _booking_values_from_offer(selected_offer)

    web3 = Web3(Web3.HTTPProvider(rpc_url))

    if not web3.is_connected():
        raise BookingClientError("Sepolia Booking ist nicht konfiguriert: RPC nicht erreichbar.")

    chain_id = web3.eth.chain_id

    if chain_id != CHAIN_ID:
        raise BookingClientError(f"Falsche Chain ID {chain_id}; erwartet {CHAIN_ID}.")

    contract = web3.eth.contract(
        address=Web3.to_checksum_address(booking_address),
        abi=abi,
    )
    nonce = web3.eth.get_transaction_count(account.address)
    tx = contract.functions.createBooking(
        booking_values["business_travel_agent_id"],
        booking_values["provider_agent_id"],
        Web3.to_checksum_address(policy_address),
        booking_values["selected_offer_id"],
        booking_values["booking_uri"],
    ).build_transaction({
        "from": account.address,
        "value": web3.to_wei(booking_values["amount_eth"], "ether"),
        "nonce": nonce,
        "chainId": CHAIN_ID,
    })

    return web3, account, contract, booking_values, tx


def submit_booking_for_offer(selected_offer: dict) -> dict:
    """Submit a Sepolia booking transaction without waiting for confirmation.

    This non-blocking variant is used by the A2A dialog path so the user gets a
    tx hash quickly and the request does not time out while waiting for mining.
    """
    web3, account, _contract, booking_values, tx = _build_booking_transaction(
        selected_offer
    )

    signed_tx = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    transaction_hash = tx_hash.hex()

    return {
        "selectedOfferId": booking_values["selected_offer_id"],
        "providerAgentId": booking_values["provider_agent_id"],
        "amountEth": booking_values["amount_eth"],
        "transactionHash": transaction_hash,
        "etherscanUrl": f"https://sepolia.etherscan.io/tx/{transaction_hash}",
        "status": "submitted",
    }


def create_booking_for_offer(selected_offer: dict) -> dict:
    """Create a Sepolia booking simulation for one selected offer.

    The caller must pass the offer selected by SmartContractClient policy
    logic. This function does not decide which offer should be booked.
    """
    web3, account, contract, booking_values, tx = _build_booking_transaction(
        selected_offer
    )

    signed_tx = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    events = contract.events.BookingCreated().process_receipt(receipt)

    if not events:
        raise BookingClientError("BookingCreated event wurde nicht gefunden.")

    booking_id = events[0]["args"]["bookingId"]
    transaction_hash = receipt["transactionHash"].hex()

    return {
        "bookingId": int(booking_id),
        "selectedOfferId": booking_values["selected_offer_id"],
        "providerAgentId": booking_values["provider_agent_id"],
        "amountEth": booking_values["amount_eth"],
        "transactionHash": transaction_hash,
        "etherscanUrl": f"https://sepolia.etherscan.io/tx/{transaction_hash}",
    }
