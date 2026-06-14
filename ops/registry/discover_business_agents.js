/**
 * discover_business_agents.js
 *
 * Read-only diagnostic: queries the BusinessAgentRegistry on Sepolia for all
 * expected capabilities (business_travel, rail, flight, mobility).
 *
 * For each capability the script shows:
 *   - agentId(s)
 *   - agentURI, owner, active flag
 *   - capabilities list
 *
 * No wallet or private key needed — read-only Sepolia calls only.
 *
 * USAGE:
 *   node ops/registry/discover_business_agents.js
 *
 * REQUIRED ENV:
 *   ALCHEMY_RPC_URL — Sepolia JSON-RPC endpoint
 */

import { createPublicClient, getContract, http } from "viem";
import { sepolia } from "viem/chains";
import fs from "node:fs";
import path from "node:path";

const CHAIN_ID = 11155111;
const DEPLOYMENT_FILE = path.join("ops", "deployments", "sepolia.json");
const ARTIFACT_FILE = path.join(
  "build",
  "hardhat",
  "artifacts",
  "contracts",
  "BusinessAgentRegistry.sol",
  "BusinessAgentRegistry.json"
);

const EXPECTED_CAPABILITIES = [
  "business_travel",
  "rail",
  "flight",
  "mobility",
];

// Minimal .env loader, kept close to the deployment/register scripts.
// Discovery is read-only and only needs ALCHEMY_RPC_URL.
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

async function printAgentsForCapability(registry, capability) {
  const agentIds = await registry.read.getAgentsByCapability([capability]);

  console.log("");
  console.log(`Capability: ${capability}`);

  if (agentIds.length === 0) {
    console.log("No agents found for this capability.");
    return false;
  }

  console.log(`Agent IDs: ${agentIds.map((agentId) => agentId.toString()).join(", ")}`);

  for (const agentId of agentIds) {
    const agent = await registry.read.getAgent([agentId]);
    const capabilities = await registry.read.getAgentCapabilities([agentId]);

    console.log(`- agentId: ${agent.agentId}`);
    console.log(`  agentURI: ${agent.agentURI}`);
    console.log(`  owner: ${agent.owner}`);
    console.log(`  active: ${agent.active}`);
    console.log(`  capabilities: ${capabilities.join(", ")}`);
  }

  return true;
}

async function main() {
  loadLocalEnv();

  const rpcUrl = requireEnv("ALCHEMY_RPC_URL");
  const registryAddress = getRegistryAddress();
  const abi = getRegistryAbi();

  const publicClient = createPublicClient({
    chain: sepolia,
    transport: http(rpcUrl),
  });

  const chainId = await publicClient.getChainId();

  if (chainId !== CHAIN_ID) {
    throw new Error(`Unexpected chain ID ${chainId}. Expected ${CHAIN_ID}.`);
  }

  const registry = getContract({
    address: registryAddress,
    abi,
    client: publicClient,
  });

  console.log(`Using BusinessAgentRegistry: ${registryAddress}`);
  console.log(`Connected chain ID: ${chainId}`);

  const discoveryResults = {};

  for (const capability of EXPECTED_CAPABILITIES) {
    discoveryResults[capability] = await printAgentsForCapability(
      registry,
      capability
    );
  }

  const missingCapabilities = EXPECTED_CAPABILITIES.filter(
    (capability) => !discoveryResults[capability]
  );

  console.log("");

  if (missingCapabilities.length === 0) {
    console.log("Discovery complete: all expected capabilities found at least one agent.");
  } else {
    console.log(
      `Discovery incomplete: no agents found for ${missingCapabilities.join(", ")}.`
    );
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
