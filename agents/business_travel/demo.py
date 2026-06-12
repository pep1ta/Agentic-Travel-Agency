# Run with: uv run python -m agents.business_travel.demo

"""Isolated smoke test for the BusinessTravelAgent.

This demo starts the three mock MCP servers if they are not already running,
then calls the BusinessTravelAgent directly. The Orchestrator and Agent
Registry are intentionally not used here.
"""

import asyncio
import socket
import sys
from pathlib import Path

from agents.business_travel.agent import BusinessTravelAgent

USER_REQUEST = "Ich muss Montag um 10 Uhr in München sein."

MCP_SERVERS = [
    ("Rail MCP Server", 8004, Path("mcp_servers") / "rail_server.py"),
    ("Flight MCP Server", 8005, Path("mcp_servers") / "flight_server.py"),
    ("Mobility MCP Server", 8006, Path("mcp_servers") / "mobility_server.py"),
]


def _is_port_open(port: int) -> bool:
    """Returns True when a local MCP server is already listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


async def _wait_for_server(name: str, port: int) -> None:
    """Waits a short time until a newly started MCP server accepts connections."""
    for _ in range(30):
        if _is_port_open(port):
            return
        await asyncio.sleep(0.2)

    raise RuntimeError(f"{name} did not start on port {port}.")


async def _start_missing_mcp_servers() -> list[asyncio.subprocess.Process]:
    """Starts mock MCP servers needed for the isolated BusinessTravelAgent flow."""
    started_processes = []

    for name, port, script_path in MCP_SERVERS:
        if _is_port_open(port):
            print(f"{name}: already running on port {port}")
            continue

        print(f"{name}: starting on port {port}")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        started_processes.append(process)
        await _wait_for_server(name, port)

    return started_processes


async def _stop_started_servers(processes: list[asyncio.subprocess.Process]) -> None:
    """Stops only the MCP server processes started by this demo."""
    for process in processes:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


async def main() -> None:
    """Runs the complete isolated demo flow."""
    started_processes = await _start_missing_mcp_servers()

    try:
        agent = BusinessTravelAgent()

        print("\nUser request:")
        print(USER_REQUEST)

        response, input_required = await agent.invoke(USER_REQUEST, context_id="business-travel-demo")

        print("\nBusinessTravelAgent response:")
        print(response)
        print(f"\nInput required: {input_required}")

    finally:
        await _stop_started_servers(started_processes)


if __name__ == "__main__":
    asyncio.run(main())
