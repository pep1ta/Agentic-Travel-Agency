# Run with: uv run python utilities/mcp/weather_server.py

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather", port=8001)


@mcp.tool()
async def get_weather(city: str) -> str:
    """Returns current weather information for a given city.

    Args:
        city: Name of the city to get weather for (e.g. "Rome", "Berlin").
    """
    url = f"https://wttr.in/{city}?format=3"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text.strip()


if __name__ == "__main__":
    mcp.run(transport="sse")