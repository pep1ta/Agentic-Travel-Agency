/**
 * register_business_provider_agents.js
 *
 * Updates the three A2A provider agents in the BusinessAgentRegistry on Sepolia
 * so each has a direct A2A base URL as its on-chain agentURI.
 *
 * CURRENT ON-CHAIN STATE:
 *   agentId=2  RailProviderAgent     agentURI=local://...  -> needs update
 *   agentId=3  FlightProviderAgent   agentURI=local://...  -> needs update
 *   agentId=4  MobilityProviderAgent agentURI=local://...  -> needs update
 *
 * WHAT THIS SCRIPT DOES:
 *   updateAgent(2, "http://localhost:10010", true)   -- Sepolia tx, costs gas
 *   updateAgent(3, "http://localhost:10011", true)   -- Sepolia tx, costs gas
 *   updateAgent(4, "http://localhost:10012", true)   -- Sepolia tx, costs gas
 *
 *   Each operation is SKIPPED if the on-chain agentURI is already correct.
 *
 * EACH OPERATION SENDS A SEPOLIA TRANSACTION AND COSTS GAS.
 * The wallet must be the owner of agentIds 2, 3, and 4 (all registered by
 * the same deployer: 0x669cADd0E9379B54fA690cE8FA9DDdE88F5a1E0D).
 *
 * USAGE:
 *
 *   Dry run — read-only, shows planned operations, sends NO transactions:
 *     node ops/registry/register_business_provider_agents.js --dry-run
 *
 *   Actual update — sends three Sepolia transactions:
 *     node ops/registry/register_business_provider_agents.js
 *
 *   Verify after update (read-only):
 *     node ops/registry/discover_business_provider_agents.js
 *
 * REQUIRED ENV (in .env or environment):
 *   ALCHEMY_RPC_URL     — Sepolia JSON-RPC endpoint
 *   WALLET_PRIVATE_KEY  — private key of 0x669cADd0E9379B54fA690cE8FA9DDdE88F5a1E0D
 *   WALLET_ADDRESS      — (optional) sanity check against derived address
 */

import {
  createPublicClient,
  createWalletClient,
  getContract,
  http,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { sepolia } from "viem/chains";
import fs from "node:fs";
import path from "node:path";

const CHAIN_ID = 11155111;
const ETHERSCAN_BASE = "https://sepolia.etherscan.io/tx/";
const DEPLOYMENT_FILE = path.join("ops", "deployments", "sepolia.json");
const ARTIFACT_FILE = path.join(
  "build",
  "hardhat",
  "artifacts",
  "contracts",
  "BusinessAgentRegistry.sol",
  "BusinessAgentRegistry.json"
);

const DRY_RUN = process.argv.includes("--dry-run");

// All three provider agents are already registered on Sepolia.
// This script updates their on-chain agentURI from the old local:// reference
// format to a direct A2A base URL so capability lookup returns a usable URL.
const PROVIDERS = [
  {
    name: "RailProviderAgent",
    capability: "rail",
    agentId: 2,
    a2aBaseUrl: "http://localhost:10010",
  },
  {
    name: "FlightProviderAgent",
    capability: "flight",
    agentId: 3,
    a2aBaseUrl: "http://localhost:10011",
  },
  {
    name: "MobilityProviderAgent",
    capability: "mobility",
    agentId: 4,
    a2aBaseUrl: "http://localhost:10012",
  },
];

// ---------------------------------------------------------------------------
// Env / config helpers (same style as other scripts in this repo)
// ---------------------------------------------------------------------------

function loadLocalEnv() {
  if (!fs.existsSync(".env")) return;

  for (const line of fs.readFileSync(".env", "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const sep = trimmed.indexOf("=");
    if (sep === -1) continue;

    const key = trimmed.slice(0, sep).trim();
    let value = trimmed.slice(sep + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

function requireEnv(name) {
  const value = process.env[name];
  if (!value || value.trim() === "") {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function normalizePrivateKey(pk) {
  if (!pk || pk.trim() === "") return undefined;
  return pk.startsWith("0x") ? pk : `0x${pk}`;
}

function assertWalletAddress(privateKey) {
  const account = privateKeyToAccount(privateKey);
  const expected = process.env.WALLET_ADDRESS;
  if (
    expected &&
    expected.trim() !== "" &&
    account.address.toLowerCase() !== expected.trim().toLowerCase()
  ) {
    throw new Error(
      "WALLET_ADDRESS does not match the address derived from WALLET_PRIVATE_KEY."
    );
  }
  return account;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function getRegistryAddress() {
  if (!fs.existsSync(DEPLOYMENT_FILE)) {
    throw new Error(`Missing deployment file: ${DEPLOYMENT_FILE}`);
  }
  const deployment = readJson(DEPLOYMENT_FILE);
  const addr = deployment.contracts?.businessAgentRegistry?.address;
  if (!addr) {
    throw new Error(
      "Missing contracts.businessAgentRegistry.address in deployments/sepolia.json."
    );
  }
  return addr;
}

function getRegistryAbi() {
  if (!fs.existsSync(ARTIFACT_FILE)) {
    throw new Error(
      `Missing artifact: ${ARTIFACT_FILE}. Run: npx hardhat test`
    );
  }
  return readJson(ARTIFACT_FILE).abi;
}

// ---------------------------------------------------------------------------
// Per-provider update logic
// ---------------------------------------------------------------------------

async function updateProviderAgent({ provider, registry, publicClient }) {
  const { name, agentId, a2aBaseUrl } = provider;

  const onChainAgent = await registry.read.getAgent([BigInt(agentId)]);

  if (onChainAgent.owner === "0x0000000000000000000000000000000000000000") {
    console.error(`  ERROR: agentId ${agentId} does not exist on chain.`);
    return;
  }

  const currentUri = onChainAgent.agentURI;
  const currentActive = onChainAgent.active;

  console.log(`\n${name} (agentId=${agentId})`);
  console.log(`  Current agentURI : ${currentUri}`);
  console.log(`  Target agentURI  : ${a2aBaseUrl}`);

  if (currentUri === a2aBaseUrl && currentActive) {
    console.log(`  Status: already correct, skipping.`);
    return;
  }

  const operation = `updateAgent(${agentId}, "${a2aBaseUrl}", true)`;

  if (DRY_RUN) {
    console.log(`  [DRY-RUN] Would call: ${operation}`);
    return;
  }

  console.log(`  Calling: ${operation}`);
  const txHash = await registry.write.updateAgent([
    BigInt(agentId),
    a2aBaseUrl,
    true,
  ]);
  await publicClient.waitForTransactionReceipt({ hash: txHash, confirmations: 1 });
  console.log(`  Transaction : ${txHash}`);
  console.log(`  Etherscan   : ${ETHERSCAN_BASE}${txHash}`);
  console.log(`  Done.`);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  loadLocalEnv();

  if (DRY_RUN) {
    console.log("DRY-RUN MODE — no transactions will be sent.\n");
  }

  const rpcUrl = requireEnv("ALCHEMY_RPC_URL");
  const registryAddress = getRegistryAddress();
  const abi = getRegistryAbi();

  console.log(`BusinessAgentRegistry: ${registryAddress}`);

  const publicClient = createPublicClient({
    chain: sepolia,
    transport: http(rpcUrl),
  });

  const chainId = await publicClient.getChainId();
  if (chainId !== CHAIN_ID) {
    throw new Error(`Expected chainId ${CHAIN_ID}, got ${chainId}.`);
  }

  let walletClient = null;
  let account = null;

  if (!DRY_RUN) {
    const privateKey = normalizePrivateKey(requireEnv("WALLET_PRIVATE_KEY"));
    account = assertWalletAddress(privateKey);
    walletClient = createWalletClient({
      account,
      chain: sepolia,
      transport: http(rpcUrl),
    });
    console.log(`Wallet: ${account.address}`);
  }

  const registry = getContract({
    address: registryAddress,
    abi,
    client: DRY_RUN
      ? publicClient
      : { public: publicClient, wallet: walletClient },
  });

  for (const provider of PROVIDERS) {
    await updateProviderAgent({ provider, registry, publicClient });
  }

  console.log(
    "\nDone. Verify with: node ops/registry/discover_business_provider_agents.js"
  );
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
