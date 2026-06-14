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
