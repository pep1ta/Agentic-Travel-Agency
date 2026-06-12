// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title BusinessTravelPolicy
/// @notice Minimal policy contract for the business travel prototype.
/// @dev This contract only selects a policy-compliant offer. It does not book,
/// pay, transfer funds, or call external systems.
contract BusinessTravelPolicy {
    uint8 public constant MODE_RAIL = 0;
    uint8 public constant MODE_FLIGHT_WITH_TRANSFERS = 1;

    uint8 public constant CLASS_SECOND = 0;
    uint8 public constant CLASS_FIRST = 1;
    uint8 public constant CLASS_ECONOMY = 2;
    uint8 public constant CLASS_BUSINESS = 3;

    uint256 public constant MAX_BUDGET = 450;
    uint256 public constant MIN_PROVIDER_REPUTATION = 70;
    uint256 public constant MIN_ARRIVAL_BUFFER_MINUTES = 30;
    uint256 public constant RAIL_PREFERRED_UNTIL_MINUTES = 480;
    uint256 public constant NO_SELECTION = type(uint256).max;

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

    /// @notice Selects the cheapest valid offer according to the business policy.
    /// @dev Rail under 8 hours is preferred. Flights can only win if no such
    /// rail option exists.
    function selectPolicyCompliantOffer(
        TravelOffer[] memory offers
    ) public pure returns (uint256 selectedIndex) {
        uint256 bestRailIndex = NO_SELECTION;
        uint256 bestRailPrice = type(uint256).max;

        for (uint256 i = 0; i < offers.length; i++) {
            if (isPreferredRailOffer(offers[i]) && offers[i].totalPrice < bestRailPrice) {
                bestRailIndex = i;
                bestRailPrice = offers[i].totalPrice;
            }
        }

        if (bestRailIndex != NO_SELECTION) {
            return bestRailIndex;
        }

        uint256 bestFlightIndex = NO_SELECTION;
        uint256 bestFlightPrice = type(uint256).max;

        for (uint256 i = 0; i < offers.length; i++) {
            if (isValidFlightOffer(offers[i]) && offers[i].totalPrice < bestFlightPrice) {
                bestFlightIndex = i;
                bestFlightPrice = offers[i].totalPrice;
            }
        }

        return bestFlightIndex;
    }

    function isPreferredRailOffer(TravelOffer memory offer) public pure returns (bool) {
        return isValidRailOffer(offer) && offer.durationMinutes <= RAIL_PREFERRED_UNTIL_MINUTES;
    }

    function isValidRailOffer(TravelOffer memory offer) public pure returns (bool) {
        return (
            offer.mode == MODE_RAIL
                && offer.travelClass == CLASS_SECOND
                && offer.totalPrice <= MAX_BUDGET
                && offer.providerReputation >= MIN_PROVIDER_REPUTATION
                && offer.arrivalBufferMinutes >= MIN_ARRIVAL_BUFFER_MINUTES
        );
    }

    function isValidFlightOffer(TravelOffer memory offer) public pure returns (bool) {
        return (
            offer.mode == MODE_FLIGHT_WITH_TRANSFERS
                && offer.travelClass == CLASS_ECONOMY
                && offer.transfersIncluded
                && offer.totalPrice <= MAX_BUDGET
                && offer.providerReputation >= MIN_PROVIDER_REPUTATION
                && offer.arrivalBufferMinutes >= MIN_ARRIVAL_BUFFER_MINUTES
        );
    }
}
