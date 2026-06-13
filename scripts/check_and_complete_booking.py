"""Check a submitted Sepolia booking transaction and complete the booking.

Usage:
    uv run python scripts/check_and_complete_booking.py --tx 0x...

The script checks the submitted createBooking transaction. If the receipt is
available, it extracts bookingId from BookingCreated and submits
completeBooking(bookingId). If the receipt is still missing, it exits with a
clear pending message.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utilities.blockchain.business_travel_booking_client import (
    BookingClientError,
    complete_booking,
    get_booking_id_from_transaction,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check and complete a submitted Sepolia BusinessTravelBooking."
    )
    parser.add_argument(
        "--tx",
        required=True,
        help="Submitted createBooking transaction hash.",
    )
    args = parser.parse_args()

    try:
        booking_result = get_booking_id_from_transaction(args.tx)

        if booking_result["status"] == "pending":
            print("Booking transaction is still pending.")
            print(f"transactionHash: {booking_result['transactionHash']}")
            print(f"Etherscan: {booking_result['etherscanUrl']}")
            return

        booking_id = booking_result["bookingId"]
        print(f"BookingCreated found for bookingId: {booking_id}")
        print(f"createBooking transaction: {booking_result['transactionHash']}")
        print(f"createBooking Etherscan: {booking_result['etherscanUrl']}")

        completion_result = complete_booking(booking_id)
        print("completeBooking submitted.")
        print(f"bookingId: {completion_result['bookingId']}")
        print(f"completionTransactionHash: {completion_result['transactionHash']}")
        print(f"completionEtherscan: {completion_result['etherscanUrl']}")

    except BookingClientError as exc:
        print(exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
