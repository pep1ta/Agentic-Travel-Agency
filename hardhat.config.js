import hardhatToolboxViemPlugin from "@nomicfoundation/hardhat-toolbox-viem";
import { defineConfig } from "hardhat/config";
import fs from "node:fs";

// Minimal .env loader for this didactic Hardhat setup.
// It intentionally uses the existing variable names only:
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
  if (privateKey === undefined || privateKey === "") {
    return undefined;
  }

  return privateKey.startsWith("0x") ? privateKey : `0x${privateKey}`;
}

loadLocalEnv();

const sepoliaRpcUrl = process.env.ALCHEMY_RPC_URL;
const walletPrivateKey = normalizePrivateKey(process.env.WALLET_PRIVATE_KEY);

const networks = {
  hardhatMainnet: {
    type: "edr-simulated",
    chainType: "l1",
  },
};

if (sepoliaRpcUrl !== undefined && walletPrivateKey !== undefined) {
  networks.sepolia = {
    type: "http",
    chainType: "l1",
    chainId: 11155111,
    url: sepoliaRpcUrl,
    accounts: [walletPrivateKey],
  };
}

export default defineConfig({
  plugins: [hardhatToolboxViemPlugin],
  solidity: {
    profiles: {
      default: {
        version: "0.8.28",
      },
    },
  },
  paths: {
    artifacts: "build/hardhat/artifacts",
    cache: "build/hardhat/cache",
    tests: "test/contracts",
  },
  networks,
});
