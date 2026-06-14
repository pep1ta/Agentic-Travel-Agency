import {
  createPublicClient,
  createWalletClient,
  getContract,
  http,
  formatEther,
  parseEventLogs,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { sepolia } from "viem/chains";
import fs from "node:fs";
import path from "node:path";

const CHAIN_ID = 11155111;
const DEPLOYMENT_FILE = path.join("ops", "deployments", "sepolia.json");
const BOOKINGS_FILE = path.join("ops", "deployments", "sepolia_bookings.json");
const ARTIFACT_FILE = path.join(
  "build",
  "hardhat",
  "artifacts",
  "contracts",
  "BusinessTravelBooking.sol",
  "BusinessTravelBooking.json"
);

const BOOKING_STATUS = [
  "Created",
  "Funded",
  "Completed",
  "Cancelled",
  "Refunded",
];

// This script completes a Sepolia booking/payment simulation.
// It does not book real travel and does not pay an external provider.
// Only existing project environment variables are used:
// ALCHEMY_RPC_URL, WALLET_PRIVATE_KEY, and WALLET_ADDRESS.
function loadLocalEnv() {
  if (!fs.existsSync(".env")) {
    return;
  }

  const lines = fs.readFileSync(".env", "utf8").split(/\r?\n/);

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed === "" || trimmed.startsWith("#")) {
      continue;
    }

    const separatorIndex = trimmed.indexOf("=");

    if (separatorIndex === -1) {
      continue;
    }

    const key = trimmed.slice(0, separatorIndex).trim();
    let value = trimmed.slice(separatorIndex + 1).trim();

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function normalizePrivateKey(privateKey) {
  if (privateKey === undefined || privateKey.trim() === "") {
    return undefined;
  }

  return privateKey.startsWith("0x") ? privateKey : `0x${privateKey}`;
}

function requireEnv(name) {
  const value = process.env[name];

  if (value === undefined || value.trim() === "") {
    throw new Error(`Missing required environment variable: ${name}`);
  }

  return value;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`);
}

function assertWalletAddress(privateKey) {
  const account = privateKeyToAccount(privateKey);
  const expectedAddress = process.env.WALLET_ADDRESS;

  if (
    expectedAddress !== undefined &&
    expectedAddress.trim() !== "" &&
    account.address.toLowerCase() !== expectedAddress.trim().toLowerCase()
  ) {
    throw new Error(
      "WALLET_ADDRESS does not match the address derived from WALLET_PRIVATE_KEY."
    );
  }

  return account;
}

function getBookingContractAddress() {
  if (!fs.existsSync(DEPLOYMENT_FILE)) {
    throw new Error(`Missing deployment file: ${DEPLOYMENT_FILE}`);
  }

  const deployment = readJson(DEPLOYMENT_FILE);
  const bookingContract = deployment.contracts?.businessTravelBooking?.address;

  if (bookingContract === undefined || bookingContract === null) {
    throw new Error(
      "Missing contracts.businessTravelBooking.address in deployments/sepolia.json."
    );
  }

  return bookingContract;
}

function getBookingAbi() {
  if (!fs.existsSync(ARTIFACT_FILE)) {
    throw new Error(
      `Missing artifact file: ${ARTIFACT_FILE}. Run npx hardhat test or npx hardhat compile first.`
    );
  }

  return readJson(ARTIFACT_FILE).abi;
}

function getStoredBookings() {
  if (!fs.existsSync(BOOKINGS_FILE)) {
    throw new Error(`Missing bookings file: ${BOOKINGS_FILE}`);
  }

  const data = readJson(BOOKINGS_FILE);

  if (!Array.isArray(data.bookings) || data.bookings.length === 0) {
    throw new Error("No bookings found in deployments/sepolia_bookings.json.");
  }

  return data;
}

function getBookingIdFromArgsOrLatest(storedBookings) {
  const bookingIdArg = process.argv[2];

  if (bookingIdArg !== undefined) {
    const bookingId = Number(bookingIdArg);

    if (!Number.isInteger(bookingId) || bookingId <= 0) {
      throw new Error("bookingId argument must be a positive integer.");
    }

    return BigInt(bookingId);
  }

  const latestBooking = storedBookings.bookings[storedBookings.bookings.length - 1];

  if (latestBooking.bookingId === undefined || latestBooking.bookingId === null) {
    throw new Error("Latest stored booking does not contain bookingId.");
  }

  return BigInt(latestBooking.bookingId);
}

function getBookingCompletedEvent(receipt, abi) {
  const events = parseEventLogs({
    abi,
    eventName: "BookingCompleted",
    logs: receipt.logs,
  });

  if (events.length === 0) {
    throw new Error("BookingCompleted event was not found in transaction receipt.");
  }

  return events[0];
}

function updateStoredBooking(storedBookings, bookingId, txHash) {
  const bookingIdNumber = Number(bookingId);
  const storedBooking = storedBookings.bookings.find(
    (booking) => booking.bookingId === bookingIdNumber
  );

  if (storedBooking === undefined) {
    throw new Error(`Booking ${bookingIdNumber} was not found in ${BOOKINGS_FILE}.`);
  }

  storedBooking.completedAt = new Date().toISOString();
  storedBooking.completionTransactionHash = txHash;
  storedBooking.status = "Completed";

  writeJson(BOOKINGS_FILE, storedBookings);
}

async function main() {
  loadLocalEnv();

  const rpcUrl = requireEnv("ALCHEMY_RPC_URL");
  const privateKey = normalizePrivateKey(requireEnv("WALLET_PRIVATE_KEY"));
  const account = assertWalletAddress(privateKey);
  const bookingContract = getBookingContractAddress();
  const abi = getBookingAbi();
  const storedBookings = getStoredBookings();
  const bookingId = getBookingIdFromArgsOrLatest(storedBookings);

  console.log(`Completing Sepolia demo booking ${bookingId}...`);
  console.log(`Caller: ${account.address}`);
  console.log(`BusinessTravelBooking: ${bookingContract}`);

  const publicClient = createPublicClient({
    chain: sepolia,
    transport: http(rpcUrl),
  });
  const walletClient = createWalletClient({
    account,
    chain: sepolia,
    transport: http(rpcUrl),
  });
  const bookingContractClient = getContract({
    address: bookingContract,
    abi,
    client: {
      public: publicClient,
      wallet: walletClient,
    },
  });

  const booking = await bookingContractClient.read.getBooking([bookingId]);
  const status = BOOKING_STATUS[booking.status] ?? `Unknown(${booking.status})`;

  console.log(`Current status: ${status}`);
  console.log(`selectedOfferId: ${booking.selectedOfferId}`);
  console.log(`amount wei: ${booking.amount}`);
  console.log(`amount ETH: ${formatEther(booking.amount)}`);

  if (status === "Completed") {
    throw new Error("Booking is already completed. No transaction was sent.");
  }

  const txHash = await bookingContractClient.write.completeBooking([bookingId]);
  const receipt = await publicClient.waitForTransactionReceipt({
    hash: txHash,
    confirmations: 1,
  });
  const event = getBookingCompletedEvent(receipt, abi);

  updateStoredBooking(storedBookings, event.args.bookingId, txHash);

  console.log(`BookingCompleted bookingId: ${event.args.bookingId}`);
  console.log(`Transaction: ${txHash}`);
  console.log(`Etherscan: https://sepolia.etherscan.io/tx/${txHash}`);
  console.log(`Updated booking data in ${BOOKINGS_FILE}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
