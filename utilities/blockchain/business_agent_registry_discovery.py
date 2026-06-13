"""Read-only discovery for the demo BusinessAgentRegistry.

This helper lets the Python Orchestrator try on-chain agent discovery first,
while keeping the existing local JSON registry as the fallback.

No private key is needed here. Discovery only reads Sepolia through
ALCHEMY_RPC_URL.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEPLOYMENT_FILE = Path("deployments/sepolia.json")
ARTIFACT_FILE = Path(
    "artifacts/contracts/BusinessAgentRegistry.sol/BusinessAgentRegistry.json"
)


def _load_local_env() -> None:
    """Minimal .env loader so this helper works like the JS scripts."""
    env_path = Path(".env")

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _read_registry_address() -> tuple[str | None, str | None]:
    if not DEPLOYMENT_FILE.exists():
        return None, f"Missing deployment file: {DEPLOYMENT_FILE}"

    deployment = json.loads(DEPLOYMENT_FILE.read_text(encoding="utf-8"))
    address = (
        deployment.get("contracts", {})
        .get("businessAgentRegistry", {})
        .get("address")
    )

    if not address:
        return None, "Missing contracts.businessAgentRegistry.address in deployments/sepolia.json."

    return address, None


def _normalize_a2a_endpoint(endpoint: str) -> str:
    suffix = "/.well-known/agent-card.json"

    if endpoint.endswith(suffix):
        return endpoint[: -len(suffix)]

    return endpoint


def _endpoint_from_local_registration(agent_uri: str) -> tuple[str | None, str | None]:
    local_prefix = "local://"

    if not agent_uri.startswith(local_prefix):
        return None, f"Unsupported agentURI for local demo discovery: {agent_uri}"

    registration_path = Path(agent_uri[len(local_prefix) :])

    if not registration_path.exists():
        return None, f"Registration file not found: {registration_path}"

    registration = json.loads(registration_path.read_text(encoding="utf-8"))

    for service in registration.get("services", []):
        if service.get("name") == "A2A" and service.get("endpoint"):
            return _normalize_a2a_endpoint(service["endpoint"]), None

    return None, f"No A2A endpoint found in {registration_path}"


def _run_node_discovery(
    rpc_url: str,
    registry_address: str,
    capability: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Use the existing Node/Viem toolchain for ABI-safe read-only calls.

    The Python environment does not include Web3/eth-abi dependencies. Calling
    Node here avoids adding a new Python dependency and keeps the fallback path
    simple.
    """
    if not ARTIFACT_FILE.exists():
        return None, f"Missing artifact file: {ARTIFACT_FILE}"

    node_script = r"""
import { createPublicClient, getContract, http } from "viem";
import { sepolia } from "viem/chains";
import fs from "node:fs";

const [rpcUrl, registryAddress, artifactFile, capability] = process.argv.slice(1);
const artifact = JSON.parse(fs.readFileSync(artifactFile, "utf8"));
const publicClient = createPublicClient({ chain: sepolia, transport: http(rpcUrl) });
const chainId = await publicClient.getChainId();

if (chainId !== 11155111) {
  throw new Error(`Unexpected chain ID ${chainId}. Expected 11155111.`);
}

const registry = getContract({
  address: registryAddress,
  abi: artifact.abi,
  client: publicClient,
});

const agentIds = await registry.read.getAgentsByCapability([capability]);
const agents = [];

for (const agentId of agentIds) {
  const agent = await registry.read.getAgent([agentId]);
  const capabilities = await registry.read.getAgentCapabilities([agentId]);

  agents.push({
    agentId: agent.agentId.toString(),
    agentURI: agent.agentURI,
    owner: agent.owner,
    active: agent.active,
    capabilities,
  });
}

console.log(JSON.stringify({ chainId, agents }));
"""

    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            node_script,
            rpc_url,
            registry_address,
            str(ARTIFACT_FILE),
            capability,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip()

    return json.loads(result.stdout), None


def discover_agent_endpoint_by_capability(
    capability: str,
) -> tuple[str | None, str | None]:
    """Return the first active A2A endpoint for a capability.

    Returns (endpoint, None) on success and (None, reason) on failure.
    """
    _load_local_env()

    rpc_url = os.environ.get("ALCHEMY_RPC_URL")

    if not rpc_url:
        return None, "ALCHEMY_RPC_URL is not set."

    registry_address, error = _read_registry_address()

    if error:
        return None, error

    discovery, error = _run_node_discovery(rpc_url, registry_address, capability)

    if error:
        return None, error

    agents = discovery.get("agents", [])

    if not agents:
        return None, f"No agents found for capability: {capability}"

    for agent in agents:
        if not agent.get("active"):
            continue

        endpoint, error = _endpoint_from_local_registration(agent["agentURI"])

        if endpoint:
            return endpoint, None

        return None, error

    return None, f"No active agents found for capability: {capability}"


def discover_business_travel_agent_endpoint() -> tuple[str | None, str | None]:
    return discover_agent_endpoint_by_capability("business_travel")
