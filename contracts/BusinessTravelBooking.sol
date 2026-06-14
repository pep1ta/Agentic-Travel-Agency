// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @notice Minimal interface for on-chain policy verification in createVerifiedBooking.
/// @dev selectPolicyCompliantOffer is declared view here; the actual BusinessTravelPolicy
/// implementation is pure, which satisfies the view requirement.
interface IBusinessTravelPolicy {
    struct TravelOffer {
        string offerId;
        uint8 mode;
        uint256 totalPrice;
        uint256 durationMinutes;
        uint8 travelClass;
        uint256 providerReputation;
        uint256 arrivalBufferMinutes;
        bool transfersIncluded;
    }

    function selectPolicyCompliantOffer(TravelOffer[] calldata offers)
        external
        view
        returns (uint256 selectedIndex);
}

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
        bool policyVerified;
        bytes32 offerHash;
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

    event VerifiedBookingCreated(
        uint256 indexed bookingId,
        uint256 indexed businessTravelAgentId,
        uint256 indexed providerAgentId,
        address requester,
        address policyContract,
        string selectedOfferId,
        uint256 amount,
        string bookingURI,
        bytes32 offerHash
    );

    event BookingCompleted(uint256 indexed bookingId);
    event BookingCancelled(uint256 indexed bookingId);
    event BookingRefunded(uint256 indexed bookingId, uint256 amount);

    uint256 private constant NO_SELECTION = type(uint256).max;

    uint256 private nextBookingId = 1;
    mapping(uint256 => Booking) private bookings;

    /// @notice Legacy: Create and fund a simulated booking without on-chain policy check.
    /// @dev The selected offer is assumed to have been checked by an off-chain policy layer
    /// before this function is called. For on-chain verification use createVerifiedBooking.
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
            status: BookingStatus.Funded,
            policyVerified: false,
            offerHash: bytes32(0)
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

    /// @notice Create and fund a booking after on-chain policy verification.
    /// @dev Calls selectPolicyCompliantOffer on the policy contract with all considered offers.
    /// Reverts if the contract returns NO_SELECTION or a different index than selectedIndex.
    /// Stores policyVerified=true and the keccak256 hash of the selected offer fields.
    function createVerifiedBooking(
        uint256 businessTravelAgentId,
        uint256 providerAgentId,
        address policyContract,
        IBusinessTravelPolicy.TravelOffer[] calldata offers,
        uint256 selectedIndex,
        string calldata bookingURI
    ) external payable returns (uint256 bookingId) {
        require(msg.value > 0, "Booking must be funded");
        require(policyContract != address(0), "Policy contract is required");
        require(offers.length > 0, "At least one offer is required");
        require(selectedIndex < offers.length, "Selected index out of range");

        uint256 contractIndex = IBusinessTravelPolicy(policyContract)
            .selectPolicyCompliantOffer(offers);

        require(contractIndex != NO_SELECTION, "Policy contract: no compliant offer");
        require(contractIndex == selectedIndex, "Policy contract: index mismatch");

        IBusinessTravelPolicy.TravelOffer calldata selected = offers[selectedIndex];

        bytes32 offerHash = keccak256(
            abi.encode(
                selected.offerId,
                selected.mode,
                selected.totalPrice,
                selected.durationMinutes,
                selected.travelClass,
                selected.providerReputation,
                selected.arrivalBufferMinutes,
                selected.transfersIncluded
            )
        );

        bookingId = nextBookingId;
        nextBookingId += 1;

        bookings[bookingId] = Booking({
            bookingId: bookingId,
            businessTravelAgentId: businessTravelAgentId,
            providerAgentId: providerAgentId,
            requester: msg.sender,
            policyContract: policyContract,
            selectedOfferId: selected.offerId,
            bookingURI: bookingURI,
            amount: msg.value,
            status: BookingStatus.Funded,
            policyVerified: true,
            offerHash: offerHash
        });

        emit VerifiedBookingCreated(
            bookingId,
            businessTravelAgentId,
            providerAgentId,
            msg.sender,
            policyContract,
            selected.offerId,
            msg.value,
            bookingURI,
            offerHash
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
