// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title BusinessTravelBooking
/// @notice A small booking/payment simulation for the business travel demo.
/// @dev This contract does not book real travel and does not pay external
/// providers. It only records that a policy-compliant offer was authorized and
/// funded in a simple on-chain escrow-like flow.
contract BusinessTravelBooking {
    enum BookingStatus {
        Created,
        Funded,
        Completed,
        Cancelled,
        Refunded
    }

    struct Booking {
        uint256 bookingId;
        uint256 businessTravelAgentId;
        uint256 providerAgentId;
        address requester;
        address policyContract;
        string selectedOfferId;
        string bookingURI;
        uint256 amount;
        BookingStatus status;
    }

    event BookingCreated(
        uint256 indexed bookingId,
        uint256 indexed businessTravelAgentId,
        uint256 indexed providerAgentId,
        address requester,
        address policyContract,
        string selectedOfferId,
        uint256 amount,
        string bookingURI
    );

    event BookingCompleted(uint256 indexed bookingId);
    event BookingCancelled(uint256 indexed bookingId);
    event BookingRefunded(uint256 indexed bookingId, uint256 amount);

    uint256 private nextBookingId = 1;
    mapping(uint256 => Booking) private bookings;

    /// @notice Create and fund a simulated booking.
    /// @dev The selected offer is assumed to have been checked by the policy
    /// layer before this function is called.
    function createBooking(
        uint256 businessTravelAgentId,
        uint256 providerAgentId,
        address policyContract,
        string calldata selectedOfferId,
        string calldata bookingURI
    ) external payable returns (uint256 bookingId) {
        require(msg.value > 0, "Booking must be funded");
        require(policyContract != address(0), "Policy contract is required");
        require(bytes(selectedOfferId).length > 0, "Selected offer is required");

        bookingId = nextBookingId;
        nextBookingId += 1;

        bookings[bookingId] = Booking({
            bookingId: bookingId,
            businessTravelAgentId: businessTravelAgentId,
            providerAgentId: providerAgentId,
            requester: msg.sender,
            policyContract: policyContract,
            selectedOfferId: selectedOfferId,
            bookingURI: bookingURI,
            amount: msg.value,
            status: BookingStatus.Funded
        });

        emit BookingCreated(
            bookingId,
            businessTravelAgentId,
            providerAgentId,
            msg.sender,
            policyContract,
            selectedOfferId,
            msg.value,
            bookingURI
        );
    }

    /// @notice Mark a funded booking as completed.
    /// @dev For this prototype, completion is open to any caller. Later
    /// versions can restrict this to provider or agent wallets.
    function completeBooking(uint256 bookingId) external {
        Booking storage booking = bookings[bookingId];

        require(booking.status == BookingStatus.Funded, "Booking is not funded");

        booking.status = BookingStatus.Completed;

        emit BookingCompleted(bookingId);
    }

    /// @notice Cancel a funded booking.
    function cancelBooking(uint256 bookingId) external {
        Booking storage booking = bookings[bookingId];

        require(msg.sender == booking.requester, "Only requester can cancel");
        require(booking.status == BookingStatus.Funded, "Booking is not funded");

        booking.status = BookingStatus.Cancelled;

        emit BookingCancelled(bookingId);
    }

    /// @notice Refund a cancelled booking to the requester.
    function refundBooking(uint256 bookingId) external {
        Booking storage booking = bookings[bookingId];

        require(msg.sender == booking.requester, "Only requester can refund");
        require(booking.status == BookingStatus.Cancelled, "Booking is not cancelled");

        uint256 amount = booking.amount;
        booking.status = BookingStatus.Refunded;
        booking.amount = 0;

        (bool success, ) = booking.requester.call{value: amount}("");
        require(success, "Refund failed");

        emit BookingRefunded(bookingId, amount);
    }

    /// @notice Read one booking.
    function getBooking(uint256 bookingId) external view returns (Booking memory) {
        return bookings[bookingId];
    }
}
