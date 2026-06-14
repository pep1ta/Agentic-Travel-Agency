/**
 * discover_business_provider_agents.js
 *
 * Read-only discovery of the three A2A provider agents in the
 * BusinessAgentRegistry on Sepolia.
 *
 * Queries capabilities: rail, flight, mobility
 *
 * For each capability the script shows:
 *   - agentId(s)
 *   - agentURI (should be http://localhost:1001x for A2A, not mcp:// or local://)
 *   - owner, active flag
 *   - URI type: A2A / legacy-local / unsupported
 *
 * No wallet or private key needed — read-only Sepolia calls only.
 *
 * USAGE:
 *   node scripts/discover_business_provider_agents.js
 *
 * REQUIRED ENV:
 *   ALCHEMY_RPC_URL — Sepolia JSON-RPC endpoint
 */

import { createPublicClient, getContract, http } from "viem";
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

// The expected A2A base URLs for each capability.
// These are also the target values set by register_business_provider_agents.js.
const EXPECTED = {
  rail: "http://localhost:10010",
  flight: "http://localhost:10011",
  mobility: "http://localhost:10012",
};

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

function classifyUri(uri) {
  if (uri.startsWith("http://") || uri.startsWith("https://")) {
    return "A2A-direct";
  }
  if (uri.startsWith("local://")) {
    return "legacy-local";
  }
  if (uri.startsWith("mcp://")) {
    return "MCP-endpoint";
  }
  return "unsupported";
}

function uriStatus(uri, expectedUri) {
  const type = classifyUri(uri);
  if (type === "A2A-direct" && uri === expectedUri) {
    return `OK  (${type})`;
  }
  if (type === "A2A-direct") {
    return `MISMATCH — expected ${expectedUri} (${type})`;
  }
  if (type === "legacy-local") {
    return `NEEDS-UPDATE — run register_business_provider_agents.js (${type})`;
  }
  if (type === "MCP-endpoint") {
    return `NEEDS-UPDATE — MCP endpoint, should be A2A`;
  }
  return `UNSUPPORTED — ${type}`;
}

async function printProviderCapability(registry, capability) {
  const expectedUri = EXPECTED[capability];
  const agentIds = await registry.read.getAgentsByCapability([capability]);

  console.log("");
  console.log(`Capability: ${capability}  (expected URI: ${expectedUri})`);

  if (agentIds.length === 0) {
    console.log("  NOT REGISTERED — run register_business_provider_agents.js");
    return false;
  }

  let allOk = true;

  for (const agentId of agentIds) {
    const agent = await registry.read.getAgent([agentId]);
    const capabilities = await registry.read.getAgentCapabilities([agentId]);
    const status = uriStatus(agent.agentURI, expectedUri);

    if (!status.startsWith("OK")) allOk = false;

    console.log(`  agentId      : ${agent.agentId}`);
    console.log(`  agentURI     : ${agent.agentURI}`);
    console.log(`  active       : ${agent.active}`);
    console.log(`  owner        : ${agent.owner}`);
    console.log(`  capabilities : ${capabilities.join(", ")}`);
    console.log(`  URI status   : ${status}`);
  }

  return allOk;
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
    throw new Error(`Expected chainId ${CHAIN_ID}, got ${chainId}.`);
  }

  const registry = getContract({
    address: registryAddress,
    abi,
    client: publicClient,
  });

  console.log(`BusinessAgentRegistry: ${registryAddress}`);
  console.log(`Chain ID             : ${chainId} (Sepolia)`);

  const results = {};
  for (const capability of Object.keys(EXPECTED)) {
    results[capability] = await printProviderCapability(registry, capability);
  }

  console.log("");

  const notReady = Object.entries(results)
    .filter(([, ok]) => !ok)
    .map(([cap]) => cap);

  if (notReady.length === 0) {
    console.log("All three provider agents registered with correct A2A URIs.");
  } else {
    console.log(
      `Needs update: ${notReady.join(", ")}.`
    );
    console.log(
      "Run: node scripts/register_business_provider_agents.js --dry-run"
    );
    console.log(
      "Then: node scripts/register_business_provider_agents.js"
    );
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
