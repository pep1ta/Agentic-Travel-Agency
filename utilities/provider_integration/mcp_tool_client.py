# utilities/provider_integration/mcp_tool_client.py

import json
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client


async def call_mcp_tool(url: str, tool_name: str, args: dict) -> Any:
    """Call a FastMCP tool over SSE and return the parsed result."""
    async with sse_client(url) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args)
            return _parse_mcp_result(result)


def _parse_mcp_result(result) -> Any:
    if not result.content:
        return []
    items = [_parse_item(item.text) for item in result.content]
    return items[0] if len(items) == 1 else items


def _parse_item(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MCP tool returned non-JSON response: {text[:200]}") from exc
