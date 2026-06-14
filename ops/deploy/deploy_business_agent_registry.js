import { network } from "hardhat";
import { privateKeyToAccount } from "viem/accounts";
import fs from "node:fs";
import path from "node:path";

const DEPLOYMENT_FILE = path.join("ops", "deployments", "sepolia.json");
const SEPOLIA_CHAIN_ID = 11155111;

// This script uses only the existing project environment variables:
// - ALCHEMY_RPC_URL: Sepolia RPC endpoint
// - WALLET_PRIVATE_KEY: deployer signer
// - WALLET_ADDRESS: optional plausibility check for the signer address
//
// Never log private keys. Only public deployment data is written to disk.
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

  return account.address;
}

function readExistingDeployment() {
  if (!fs.existsSync(DEPLOYMENT_FILE)) {
    return {
      network: "sepolia",
      chainId: SEPOLIA_CHAIN_ID,
      contracts: {},
    };
  }

  return JSON.parse(fs.readFileSync(DEPLOYMENT_FILE, "utf8"));
}

function writeDeployment(deployment) {
  fs.mkdirSync(path.dirname(DEPLOYMENT_FILE), { recursive: true });
  fs.writeFileSync(DEPLOYMENT_FILE, `${JSON.stringify(deployment, null, 2)}\n`);
}

async function main() {
  loadLocalEnv();

  requireEnv("ALCHEMY_RPC_URL");
  const privateKey = normalizePrivateKey(requireEnv("WALLET_PRIVATE_KEY"));
  const deployer = assertWalletAddress(privateKey);

  console.log("Deploying BusinessAgentRegistry to Sepolia...");
  console.log(`Deployer: ${deployer}`);

  const { viem } = await network.create("sepolia");
  const publicClient = await viem.getPublicClient();
  const { contract, deploymentTransaction } =
    await viem.sendDeploymentTransaction("BusinessAgentRegistry");

  const receipt = await publicClient.waitForTransactionReceipt({
    hash: deploymentTransaction.hash,
    confirmations: 1,
  });

  if (receipt.contractAddress === null || receipt.contractAddress === undefined) {
    throw new Error("Deployment transaction did not create a contract address.");
  }

  const deployment = readExistingDeployment();

  deployment.network = "sepolia";
  deployment.chainId = SEPOLIA_CHAIN_ID;
  deployment.contracts = deployment.contracts ?? {};
  deployment.contracts.businessAgentRegistry = {
    address: contract.address,
    deploymentTx: deploymentTransaction.hash,
  };
  deployment.deployer = deployer;
  deployment.updatedAt = new Date().toISOString();

  writeDeployment(deployment);

  console.log(`BusinessAgentRegistry deployed at: ${contract.address}`);
  console.log(`Deployment transaction: ${deploymentTransaction.hash}`);
  console.log(`Saved deployment data to ${DEPLOYMENT_FILE}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
