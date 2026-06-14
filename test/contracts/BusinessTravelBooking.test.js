import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { network } from "hardhat";

const STATUS_FUNDED = 1;
const STATUS_COMPLETED = 2;
const STATUS_CANCELLED = 3;
const STATUS_REFUNDED = 4;

const BOOKING_AMOUNT = 1_000_000_000_000_000_000n;
const BUSINESS_TRAVEL_AGENT_ID = 1n;
const PROVIDER_AGENT_ID = 2n;
const POLICY_CONTRACT = "0x0000000000000000000000000000000000000001";
const SELECTED_OFFER_ID = "rail-1";
const BOOKING_URI = "local://bookings/demo-booking-1.json";

async function deployBookingFixture() {
  const { viem } = await network.create();
  const [requester, otherUser] = await viem.getWalletClients();
  const publicClient = await viem.getPublicClient();
  const booking = await viem.deployContract("BusinessTravelBooking");

  return { booking, requester, otherUser, publicClient };
}

async function createBooking(booking, options = {}) {
  const {
    businessTravelAgentId = BUSINESS_TRAVEL_AGENT_ID,
    providerAgentId = PROVIDER_AGENT_ID,
    policyContract = POLICY_CONTRACT,
    selectedOfferId = SELECTED_OFFER_ID,
    bookingURI = BOOKING_URI,
    value = BOOKING_AMOUNT,
    account,
  } = options;

  return await booking.write.createBooking(
    [
      businessTravelAgentId,
      providerAgentId,
      policyContract,
      selectedOfferId,
      bookingURI,
    ],
    { value, account }
  );
}

// ---------------------------------------------------------------------------
// Offers for createVerifiedBooking tests.
// Must satisfy BusinessTravelPolicy.sol constants:
//   MAX_BUDGET=450, MIN_PROVIDER_REPUTATION=70, MIN_ARRIVAL_BUFFER=30,
//   RAIL_PREFERRED_UNTIL_MINUTES=480, MODE_RAIL=0, CLASS_SECOND=0
// ---------------------------------------------------------------------------

const OFFER_RAIL_VALID = {
  offerId: "rail-test-1",
  mode: 0,
  totalPrice: 119n,
  durationMinutes: 395n,
  travelClass: 0,
  providerReputation: 82n,
  arrivalBufferMinutes: 75n,
  transfersIncluded: false,
};

const OFFER_RAIL_EXPENSIVE = {
  offerId: "rail-test-2",
  mode: 0,
  totalPrice: 200n,
  durationMinutes: 300n,
  travelClass: 0,
  providerReputation: 80n,
  arrivalBufferMinutes: 60n,
  transfersIncluded: false,
};

const OFFER_RAIL_OVER_BUDGET = {
  offerId: "rail-over-budget",
  mode: 0,
  totalPrice: 600n,
  durationMinutes: 300n,
  travelClass: 0,
  providerReputation: 80n,
  arrivalBufferMinutes: 60n,
  transfersIncluded: false,
};

async function deployVerifiedFixture() {
  const { viem } = await network.create();
  const [requester, otherUser] = await viem.getWalletClients();
  const publicClient = await viem.getPublicClient();
  const policy = await viem.deployContract("BusinessTravelPolicy");
  const booking = await viem.deployContract("BusinessTravelBooking");

  return { booking, policy, requester, otherUser, publicClient };
}

describe("BusinessTravelBooking", () => {
  it("creates a booking with ETH", async () => {
    const { booking } = await deployBookingFixture();

    await createBooking(booking);

    const storedBooking = await booking.read.getBooking([1n]);

    assert.equal(storedBooking.bookingId, 1n);
  });

  it("stores booking details correctly", async () => {
    const { booking, requester } = await deployBookingFixture();

    await createBooking(booking);

    const storedBooking = await booking.read.getBooking([1n]);

    assert.equal(storedBooking.bookingId, 1n);
    assert.equal(storedBooking.businessTravelAgentId, BUSINESS_TRAVEL_AGENT_ID);
    assert.equal(storedBooking.providerAgentId, PROVIDER_AGENT_ID);
    assert.equal(storedBooking.requester.toLowerCase(), requester.account.address.toLowerCase());
    assert.equal(storedBooking.policyContract.toLowerCase(), POLICY_CONTRACT.toLowerCase());
    assert.equal(storedBooking.selectedOfferId, SELECTED_OFFER_ID);
    assert.equal(storedBooking.bookingURI, BOOKING_URI);
    assert.equal(storedBooking.amount, BOOKING_AMOUNT);
    assert.equal(storedBooking.status, STATUS_FUNDED);
  });

  it("reverts when creating a booking without ETH", async () => {
    const { booking } = await deployBookingFixture();

    await assert.rejects(createBooking(booking, { value: 0n }));
  });

  it("reverts when policyContract is zero address", async () => {
    const { booking } = await deployBookingFixture();

    await assert.rejects(
      createBooking(booking, {
        policyContract: "0x0000000000000000000000000000000000000000",
      })
    );
  });

  it("reverts when selectedOfferId is empty", async () => {
    const { booking } = await deployBookingFixture();

    await assert.rejects(createBooking(booking, { selectedOfferId: "" }));
  });

  it("completes a funded booking", async () => {
    const { booking } = await deployBookingFixture();

    await createBooking(booking);
    await booking.write.completeBooking([1n]);

    const storedBooking = await booking.read.getBooking([1n]);

    assert.equal(storedBooking.status, STATUS_COMPLETED);
  });

  it("allows requester to cancel a funded booking", async () => {
    const { booking } = await deployBookingFixture();

    await createBooking(booking);
    await booking.write.cancelBooking([1n]);

    const storedBooking = await booking.read.getBooking([1n]);

    assert.equal(storedBooking.status, STATUS_CANCELLED);
  });

  it("does not allow a non-requester to cancel", async () => {
    const { booking, otherUser } = await deployBookingFixture();

    await createBooking(booking);

    await assert.rejects(
      booking.write.cancelBooking([1n], { account: otherUser.account })
    );
  });

  it("refunds a cancelled booking", async () => {
    const { booking } = await deployBookingFixture();

    await createBooking(booking);
    await booking.write.cancelBooking([1n]);
    await booking.write.refundBooking([1n]);

    const storedBooking = await booking.read.getBooking([1n]);

    assert.equal(storedBooking.status, STATUS_REFUNDED);
  });

  it("returns ETH to the requester on refund", async () => {
    const { booking, requester, publicClient } = await deployBookingFixture();

    await createBooking(booking);
    await booking.write.cancelBooking([1n]);

    const balanceBeforeRefund = await publicClient.getBalance({
      address: requester.account.address,
    });

    await booking.write.refundBooking([1n]);

    const balanceAfterRefund = await publicClient.getBalance({
      address: requester.account.address,
    });
    const contractBalance = await publicClient.getBalance({
      address: booking.address,
    });

    assert.equal(contractBalance, 0n);
    assert.equal(balanceAfterRefund > balanceBeforeRefund, true);
  });

  it("does not allow a completed booking to be cancelled", async () => {
    const { booking } = await deployBookingFixture();

    await createBooking(booking);
    await booking.write.completeBooking([1n]);

    await assert.rejects(booking.write.cancelBooking([1n]));
  });

  it("does not allow a refunded booking to be refunded again", async () => {
    const { booking } = await deployBookingFixture();

    await createBooking(booking);
    await booking.write.cancelBooking([1n]);
    await booking.write.refundBooking([1n]);

    await assert.rejects(booking.write.refundBooking([1n]));
  });
});

describe("BusinessTravelBooking — createVerifiedBooking", () => {
  it("creates a verified booking when policy confirms the index", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await booking.write.createVerifiedBooking(
      [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_VALID], 0n, BOOKING_URI],
      { value: BOOKING_AMOUNT }
    );

    const stored = await booking.read.getBooking([1n]);
    assert.equal(stored.bookingId, 1n);
  });

  it("stores policyVerified=true", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await booking.write.createVerifiedBooking(
      [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_VALID], 0n, BOOKING_URI],
      { value: BOOKING_AMOUNT }
    );

    const stored = await booking.read.getBooking([1n]);
    assert.equal(stored.policyVerified, true);
  });

  it("stores selectedOfferId from the offer at selectedIndex", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await booking.write.createVerifiedBooking(
      [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_VALID], 0n, BOOKING_URI],
      { value: BOOKING_AMOUNT }
    );

    const stored = await booking.read.getBooking([1n]);
    assert.equal(stored.selectedOfferId, OFFER_RAIL_VALID.offerId);
  });

  it("stores a non-zero offerHash", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await booking.write.createVerifiedBooking(
      [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_VALID], 0n, BOOKING_URI],
      { value: BOOKING_AMOUNT }
    );

    const stored = await booking.read.getBooking([1n]);
    assert.notEqual(stored.offerHash, "0x0000000000000000000000000000000000000000000000000000000000000000");
  });

  it("stores status=Funded", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await booking.write.createVerifiedBooking(
      [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_VALID], 0n, BOOKING_URI],
      { value: BOOKING_AMOUNT }
    );

    const stored = await booking.read.getBooking([1n]);
    assert.equal(stored.status, STATUS_FUNDED);
  });

  it("selects cheapest offer when two valid rail offers are given", async () => {
    const { booking, policy } = await deployVerifiedFixture();
    // policy selects index 0 (OFFER_RAIL_VALID at 119) over index 1 (OFFER_RAIL_EXPENSIVE at 200)
    await booking.write.createVerifiedBooking(
      [
        BUSINESS_TRAVEL_AGENT_ID,
        PROVIDER_AGENT_ID,
        policy.address,
        [OFFER_RAIL_VALID, OFFER_RAIL_EXPENSIVE],
        0n,
        BOOKING_URI,
      ],
      { value: BOOKING_AMOUNT }
    );

    const stored = await booking.read.getBooking([1n]);
    assert.equal(stored.selectedOfferId, OFFER_RAIL_VALID.offerId);
    assert.equal(stored.policyVerified, true);
  });

  it("reverts when selectedIndex is out of range", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await assert.rejects(
      booking.write.createVerifiedBooking(
        [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_VALID], 5n, BOOKING_URI],
        { value: BOOKING_AMOUNT }
      )
    );
  });

  it("reverts when policy returns NO_SELECTION (no compliant offer)", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await assert.rejects(
      booking.write.createVerifiedBooking(
        [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_OVER_BUDGET], 0n, BOOKING_URI],
        { value: BOOKING_AMOUNT }
      )
    );
  });

  it("reverts when selectedIndex does not match the policy contract result", async () => {
    const { booking, policy } = await deployVerifiedFixture();
    // policy selects index 0 (cheapest), caller claims index 1
    await assert.rejects(
      booking.write.createVerifiedBooking(
        [
          BUSINESS_TRAVEL_AGENT_ID,
          PROVIDER_AGENT_ID,
          policy.address,
          [OFFER_RAIL_VALID, OFFER_RAIL_EXPENSIVE],
          1n,
          BOOKING_URI,
        ],
        { value: BOOKING_AMOUNT }
      )
    );
  });

  it("reverts when not funded", async () => {
    const { booking, policy } = await deployVerifiedFixture();

    await assert.rejects(
      booking.write.createVerifiedBooking(
        [BUSINESS_TRAVEL_AGENT_ID, PROVIDER_AGENT_ID, policy.address, [OFFER_RAIL_VALID], 0n, BOOKING_URI],
        { value: 0n }
      )
    );
  });

  it("reverts when policyContract is zero address", async () => {
    const { booking } = await deployVerifiedFixture();

    await assert.rejects(
      booking.write.createVerifiedBooking(
        [
          BUSINESS_TRAVEL_AGENT_ID,
          PROVIDER_AGENT_ID,
          "0x0000000000000000000000000000000000000000",
          [OFFER_RAIL_VALID],
          0n,
          BOOKING_URI,
        ],
        { value: BOOKING_AMOUNT }
      )
    );
  });
});
