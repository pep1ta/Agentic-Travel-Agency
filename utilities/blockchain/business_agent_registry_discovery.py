"""Read-only discovery for the demo BusinessAgentRegistry.

Resolves a capability name to an A2A base URL via Sepolia on-chain data.

No private key is needed — discovery is read-only.

Supported on-chain agentURI formats:
  http://...  — direct A2A base URL (used by provider agents after migration)
  local://... — pointer to a local registration JSON file whose services[A2A]
                holds the actual endpoint (used by business_travel_agent)

Usage:
  from utilities.blockchain.business_agent_registry_discovery import (
      discover_agent_endpoint_by_capability,
      discover_all_provider_endpoints,
  )
  url, err = discover_agent_endpoint_by_capability("rail")
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEPLOYMENT_FILE = Path("ops/deployments/sepolia.json")
ARTIFACT_FILE = Path(
    "build/hardhat/artifacts/contracts/BusinessAgentRegistry.sol/BusinessAgentRegistry.json"
)

# Fallback endpoints for local-only demo (no Sepolia required).
# These are used when ALCHEMY_RPC_URL is not set or the chain cannot be reached.
LOCAL_FALLBACK_ENDPOINTS: dict[str, str] = {
    "rail": "http://localhost:10010",
    "flight": "http://localhost:10011",
    "mobility": "http://localhost:10012",
    "business_travel": "http://localhost:10004",
}


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
    """Strips /.well-known/agent-card.json suffix if present."""
    suffix = "/.well-known/agent-card.json"
    if endpoint.endswith(suffix):
        return endpoint[: -len(suffix)]
    return endpoint


def _endpoint_from_agentURI(agent_uri: str) -> tuple[str | None, str | None]:
    """Resolves an on-chain agentURI to a usable A2A base URL.

    Two formats are supported:

    Direct HTTP (new format, used by provider agents after migration):
      http://localhost:10010  ->  returned as-is (normalized)

    Local file reference (legacy format, used by business_travel_agent):
      local://utilities/blockchain/registrations/business_travel_agent.json
      -> reads the file, finds services[name=A2A].endpoint, normalizes suffix
    """
    if agent_uri.startswith("http://") or agent_uri.startswith("https://"):
        return _normalize_a2a_endpoint(agent_uri), None

    if agent_uri.startswith("local://"):
        return _endpoint_from_local_registration(agent_uri)

    return None, f"Unsupported agentURI format: {agent_uri!r}"


def _endpoint_from_local_registration(agent_uri: str) -> tuple[str | None, str | None]:
    """Resolves a local:// agentURI by reading the local registration file."""
    local_prefix = "local://"
    if not agent_uri.startswith(local_prefix):
        return None, f"Not a local:// URI: {agent_uri}"

    registration_path = Path(agent_uri[len(local_prefix):])
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
    """Queries the on-chain registry via Node/Viem for ABI-safe read-only calls.

    The Python environment does not include Web3/eth-abi dependencies. Calling
    Node here avoids adding a Python blockchain dependency and keeps this module
    lightweight.
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

    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"Node output is not valid JSON: {exc}"


def discover_agent_endpoint_by_capability(
    capability: str,
    *,
    use_fallback: bool = False,
) -> tuple[str | None, str | None]:
    """Returns the first active A2A base URL for a capability.

    Queries the BusinessAgentRegistry on Sepolia via ALCHEMY_RPC_URL.
    Resolves the on-chain agentURI (http:// or local://) to a base URL.

    Returns (endpoint, None) on success and (None, reason) on failure.

    use_fallback=False (default, required for production):
        Returns (None, reason) on any failure. BusinessTravelAgent and
        verify_business_travel.py always use this — the agent must not silently
        substitute a local URL when registry discovery fails.

    use_fallback=True (diagnostic scripts only):
        Returns LOCAL_FALLBACK_ENDPOINTS[capability] instead of an error when
        discovery fails. Only for manual local debugging and diagnostic helpers
        (discover_business_provider_agents.js, manual CLI checks). NEVER use
        this in BusinessTravelAgent or in verify_business_travel.py.
    """
    _load_local_env()

    rpc_url = os.environ.get("ALCHEMY_RPC_URL")
    if not rpc_url:
        if use_fallback and capability in LOCAL_FALLBACK_ENDPOINTS:
            return LOCAL_FALLBACK_ENDPOINTS[capability], None
        return None, "ALCHEMY_RPC_URL is not set."

    registry_address, error = _read_registry_address()
    if error:
        if use_fallback and capability in LOCAL_FALLBACK_ENDPOINTS:
            return LOCAL_FALLBACK_ENDPOINTS[capability], None
        return None, error

    discovery, error = _run_node_discovery(rpc_url, registry_address, capability)
    if error:
        if use_fallback and capability in LOCAL_FALLBACK_ENDPOINTS:
            return LOCAL_FALLBACK_ENDPOINTS[capability], None
        return None, error

    agents = discovery.get("agents", [])
    if not agents:
        if use_fallback and capability in LOCAL_FALLBACK_ENDPOINTS:
            return LOCAL_FALLBACK_ENDPOINTS[capability], None
        return None, f"No agents found for capability: {capability}"

    for agent in agents:
        if not agent.get("active"):
            continue
        endpoint, err = _endpoint_from_agentURI(agent["agentURI"])
        if endpoint:
            return endpoint, None
        return None, err

    if use_fallback and capability in LOCAL_FALLBACK_ENDPOINTS:
        return LOCAL_FALLBACK_ENDPOINTS[capability], None
    return None, f"No active agents found for capability: {capability}"


def discover_all_provider_endpoints(
    *,
    use_fallback: bool = False,
) -> dict[str, tuple[str | None, str | None]]:
    """Returns endpoints for all three A2A provider capabilities.

    Returns a dict: capability -> (endpoint, error).

    use_fallback=False is required for BusinessTravelAgent and verify_business_travel.py.
    use_fallback=True is only for diagnostic scripts — see discover_agent_endpoint_by_capability.
    """
    return {
        capability: discover_agent_endpoint_by_capability(
            capability, use_fallback=use_fallback
        )
        for capability in ("rail", "flight", "mobility")
    }


def discover_business_travel_agent_endpoint() -> tuple[str | None, str | None]:
    return discover_agent_endpoint_by_capability("business_travel")
