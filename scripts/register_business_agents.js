import {
  createPublicClient,
  createWalletClient,
  getContract,
  http,
  parseEventLogs,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { sepolia } from "viem/chains";
import fs from "node:fs";
import path from "node:path";

const CHAIN_ID = 11155111;
const DEPLOYMENT_FILE = path.join("deployments", "sepolia.json");
const ARTIFACT_FILE = path.join(
  "artifacts",
  "contracts",
  "BusinessAgentRegistry.sol",
  "BusinessAgentRegistry.json"
);

const REGISTRATION_FILES = [
  {
    path: path.join(
      "utilities",
      "blockchain",
      "registrations",
      "business_travel_agent.json"
    ),
    agentURI:
      "local://utilities/blockchain/registrations/business_travel_agent.json",
  },
  {
    path: path.join(
      "utilities",
      "blockchain",
      "registrations",
      "rail_provider_agent.json"
    ),
    agentURI:
      "local://utilities/blockchain/registrations/rail_provider_agent.json",
  },
  {
    path: path.join(
      "utilities",
      "blockchain",
      "registrations",
      "flight_provider_agent.json"
    ),
    agentURI:
      "local://utilities/blockchain/registrations/flight_provider_agent.json",
  },
  {
    path: path.join(
      "utilities",
      "blockchain",
      "registrations",
      "mobility_provider_agent.json"
    ),
    agentURI:
      "local://utilities/blockchain/registrations/mobility_provider_agent.json",
  },
];

// Minimal .env loader, kept close to the deployment script style.
// Only existing variables are used:
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

function getRegistryAddress() {
  if (!fs.existsSync(DEPLOYMENT_FILE)) {
    throw new Error(`Missing deployment file: ${DEPLOYMENT_FILE}`);
  }

  const deployment = readJson(DEPLOYMENT_FILE);
  const registryAddress =
    deployment.contracts?.businessAgentRegistry?.address;

  if (registryAddress === undefined || registryAddress === null) {
    throw new Error(
      "Missing contracts.businessAgentRegistry.address in deployments/sepolia.json."
    );
  }

  return registryAddress;
}

function getRegistryAbi() {
  if (!fs.existsSync(ARTIFACT_FILE)) {
    throw new Error(
      `Missing artifact file: ${ARTIFACT_FILE}. Run npx hardhat test or npx hardhat compile first.`
    );
  }

  return readJson(ARTIFACT_FILE).abi;
}

function getAgentIdFromReceipt(receipt, abi) {
  const events = parseEventLogs({
    abi,
    eventName: "AgentRegistered",
    logs: receipt.logs,
  });

  if (events.length === 0) {
    throw new Error("AgentRegistered event was not found in transaction receipt.");
  }

  return events[0].args.agentId;
}

async function registerAgent({
  registrationFile,
  agentURI,
  registry,
  publicClient,
  abi,
  registryAddress,
}) {
  const registration = readJson(registrationFile);
  const existingAgentId = registration.registrations?.[0]?.agentId;

  if (existingAgentId !== null && existingAgentId !== undefined) {
    console.log(
      `Skipping ${registration.name}: already registered as agentId ${existingAgentId}.`
    );
    return;
  }

  const capabilities = registration.capabilities ?? [];

  console.log(`Registering ${registration.name}...`);

  const txHash = await registry.write.register([agentURI, capabilities]);
  const receipt = await publicClient.waitForTransactionReceipt({
    hash: txHash,
    confirmations: 1,
  });
  const agentId = getAgentIdFromReceipt(receipt, abi);

  registration.registrations = [
    {
      agentId: Number(agentId),
      agentRegistry: `eip155:${CHAIN_ID}:${registryAddress}`,
    },
  ];

  writeJson(registrationFile, registration);

  console.log(`Registered ${registration.name} as agentId ${agentId}.`);
  console.log(`Transaction: ${txHash}`);
  console.log(`Etherscan: https://sepolia.etherscan.io/tx/${txHash}`);
}

async function main() {
  loadLocalEnv();

  const rpcUrl = requireEnv("ALCHEMY_RPC_URL");
  const privateKey = normalizePrivateKey(requireEnv("WALLET_PRIVATE_KEY"));
  const account = assertWalletAddress(privateKey);
  const registryAddress = getRegistryAddress();
  const abi = getRegistryAbi();

  console.log(`Using BusinessAgentRegistry: ${registryAddress}`);
  console.log(`Registrant wallet: ${account.address}`);

  const publicClient = createPublicClient({
    chain: sepolia,
    transport: http(rpcUrl),
  });
  const walletClient = createWalletClient({
    account,
    chain: sepolia,
    transport: http(rpcUrl),
  });
  const registry = getContract({
    address: registryAddress,
    abi,
    client: {
      public: publicClient,
      wallet: walletClient,
    },
  });

  for (const item of REGISTRATION_FILES) {
    await registerAgent({
      registrationFile: item.path,
      agentURI: item.agentURI,
      registry,
      publicClient,
      abi,
      registryAddress,
    });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
