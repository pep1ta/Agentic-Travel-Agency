import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { network } from "hardhat";

const MODE_RAIL = 0;
const MODE_FLIGHT_WITH_TRANSFERS = 1;

const CLASS_SECOND = 0;
const CLASS_FIRST = 1;
const CLASS_ECONOMY = 2;

const NO_SELECTION = (1n << 256n) - 1n;

function railOffer(overrides = {}) {
  return {
    offerId: "rail-1",
    mode: MODE_RAIL,
    totalPrice: 119,
    durationMinutes: 395,
    travelClass: CLASS_SECOND,
    providerReputation: 82,
    arrivalBufferMinutes: 75,
    transfersIncluded: true,
    ...overrides,
  };
}

function flightOffer(overrides = {}) {
  return {
    offerId: "flight-1-with-transfers",
    mode: MODE_FLIGHT_WITH_TRANSFERS,
    totalPrice: 216,
    durationMinutes: 185,
    travelClass: CLASS_ECONOMY,
    providerReputation: 88,
    arrivalBufferMinutes: 60,
    transfersIncluded: true,
    ...overrides,
  };
}

async function deployPolicy() {
  const { viem } = await network.create();
  return await viem.deployContract("BusinessTravelPolicy");
}

describe("BusinessTravelPolicy", () => {
  it("rail under 8h wins over flight", async () => {
    const policy = await deployPolicy();
    const selectedIndex = await policy.read.selectPolicyCompliantOffer([[
      railOffer(),
      flightOffer({ totalPrice: 90 }),
    ]]);

    assert.equal(selectedIndex, 0n);
  });

  it("long rail allows flight", async () => {
    const policy = await deployPolicy();
    const selectedIndex = await policy.read.selectPolicyCompliantOffer([[
      railOffer({ durationMinutes: 560 }),
      flightOffer(),
    ]]);

    assert.equal(selectedIndex, 1n);
  });

  it("first class rail is invalid", async () => {
    const policy = await deployPolicy();
    const selectedIndex = await policy.read.selectPolicyCompliantOffer([[
      railOffer({ travelClass: CLASS_FIRST }),
      flightOffer(),
    ]]);

    assert.equal(selectedIndex, 1n);
  });

  it("flight without transfers is invalid", async () => {
    const policy = await deployPolicy();
    const selectedIndex = await policy.read.selectPolicyCompliantOffer([[
      railOffer({ durationMinutes: 560 }),
      flightOffer({ transfersIncluded: false }),
    ]]);

    assert.equal(selectedIndex, NO_SELECTION);
  });

  it("provider reputation below 70 is invalid", async () => {
    const policy = await deployPolicy();
    const selectedIndex = await policy.read.selectPolicyCompliantOffer([[
      railOffer({ providerReputation: 69 }),
      flightOffer({ providerReputation: 69 }),
    ]]);

    assert.equal(selectedIndex, NO_SELECTION);
  });

  it("no valid offer returns NO_SELECTION", async () => {
    const policy = await deployPolicy();
    const selectedIndex = await policy.read.selectPolicyCompliantOffer([[
      railOffer({ travelClass: CLASS_FIRST, providerReputation: 60 }),
      flightOffer({ transfersIncluded: false, providerReputation: 60 }),
    ]]);

    assert.equal(selectedIndex, NO_SELECTION);
  });
});
