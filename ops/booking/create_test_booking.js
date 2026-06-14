import {
  createPublicClient,
  createWalletClient,
  getContract,
  http,
  parseEther,
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

const DEMO_BOOKING = {
  businessTravelAgentId: 1n,
  providerAgentId: 2n,
  selectedOfferId: "rail-1",
  bookingURI: "local://bookings/business-travel/rail-1-demo",
  amountEth: "0.0001",
};

// This script creates a Sepolia booking/payment simulation.
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

function getDeploymentContracts() {
  if (!fs.existsSync(DEPLOYMENT_FILE)) {
    throw new Error(`Missing deployment file: ${DEPLOYMENT_FILE}`);
  }

  const deployment = readJson(DEPLOYMENT_FILE);
  const bookingContract = deployment.contracts?.businessTravelBooking?.address;
  const policyContract = deployment.contracts?.businessTravelPolicy?.address;

  if (bookingContract === undefined || bookingContract === null) {
    throw new Error(
      "Missing contracts.businessTravelBooking.address in deployments/sepolia.json."
    );
  }

  if (policyContract === undefined || policyContract === null) {
    throw new Error(
      "Missing contracts.businessTravelPolicy.address in deployments/sepolia.json."
    );
  }

  return { bookingContract, policyContract };
}

function getBookingAbi() {
  if (!fs.existsSync(ARTIFACT_FILE)) {
    throw new Error(
      `Missing artifact file: ${ARTIFACT_FILE}. Run npx hardhat test or npx hardhat compile first.`
    );
  }

  return readJson(ARTIFACT_FILE).abi;
}

function getBookingCreatedEvent(receipt, abi) {
  const events = parseEventLogs({
    abi,
    eventName: "BookingCreated",
    logs: receipt.logs,
  });

  if (events.length === 0) {
    throw new Error("BookingCreated event was not found in transaction receipt.");
  }

  return events[0];
}

function readExistingBookings() {
  if (!fs.existsSync(BOOKINGS_FILE)) {
    return {
      network: "sepolia",
      chainId: CHAIN_ID,
      bookings: [],
    };
  }

  return readJson(BOOKINGS_FILE);
}

async function main() {
  loadLocalEnv();

  const rpcUrl = requireEnv("ALCHEMY_RPC_URL");
  const privateKey = normalizePrivateKey(requireEnv("WALLET_PRIVATE_KEY"));
  const account = assertWalletAddress(privateKey);
  const { bookingContract, policyContract } = getDeploymentContracts();
  const abi = getBookingAbi();

  console.log("Creating Sepolia demo booking for selected offer rail-1...");
  console.log(`Requester: ${account.address}`);
  console.log(`BusinessTravelBooking: ${bookingContract}`);
  console.log(`BusinessTravelPolicy: ${policyContract}`);

  const publicClient = createPublicClient({
    chain: sepolia,
    transport: http(rpcUrl),
  });
  const walletClient = createWalletClient({
    account,
    chain: sepolia,
    transport: http(rpcUrl),
  });
  const booking = getContract({
    address: bookingContract,
    abi,
    client: {
      public: publicClient,
      wallet: walletClient,
    },
  });

  const txHash = await booking.write.createBooking(
    [
      DEMO_BOOKING.businessTravelAgentId,
      DEMO_BOOKING.providerAgentId,
      policyContract,
      DEMO_BOOKING.selectedOfferId,
      DEMO_BOOKING.bookingURI,
    ],
    {
      value: parseEther(DEMO_BOOKING.amountEth),
    }
  );

  const receipt = await publicClient.waitForTransactionReceipt({
    hash: txHash,
    confirmations: 1,
  });
  const event = getBookingCreatedEvent(receipt, abi);
  const bookingId = event.args.bookingId;
  const amount = event.args.amount;

  const bookings = readExistingBookings();

  bookings.network = "sepolia";
  bookings.chainId = CHAIN_ID;
  bookings.bookings = bookings.bookings ?? [];
  bookings.bookings.push({
    bookingId: Number(bookingId),
    selectedOfferId: DEMO_BOOKING.selectedOfferId,
    businessTravelAgentId: Number(DEMO_BOOKING.businessTravelAgentId),
    providerAgentId: Number(DEMO_BOOKING.providerAgentId),
    policyContract,
    bookingContract,
    bookingURI: DEMO_BOOKING.bookingURI,
    amountEth: DEMO_BOOKING.amountEth,
    transactionHash: txHash,
    createdAt: new Date().toISOString(),
  });

  writeJson(BOOKINGS_FILE, bookings);

  console.log(`BookingCreated bookingId: ${bookingId}`);
  console.log(`Amount wei: ${amount}`);
  console.log(`Transaction: ${txHash}`);
  console.log(`Etherscan: https://sepolia.etherscan.io/tx/${txHash}`);
  console.log(`Saved booking data to ${BOOKINGS_FILE}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
