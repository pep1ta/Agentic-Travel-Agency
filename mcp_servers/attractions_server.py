# mcp_servers/attractions_server.py

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("attractions", port=8002)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "TravelAgencyBot/1.0"}


async def _get_city_bbox(city: str) -> tuple[float, float, float, float]:
    """Fetches bounding box coordinates for a city using Nominatim."""
    async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
        response = await client.get(
            NOMINATIM_URL,
            params={"q": city, "format": "json", "limit": 1},
        )
        response.raise_for_status()
        results = response.json()

    if not results:
        raise ValueError(f"City not found: {city}")

    bbox = results[0]["boundingbox"]
    # bbox is [south, north, west, east]
    return float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])


@mcp.tool()
async def get_attractions(city: str, limit: int = 10) -> str:
    """Returns a list of tourist attractions for a given city.

    Args:
        city: Name of the city to search attractions in (e.g. "Rome", "Berlin").
        limit: Maximum number of attractions to return (default 10).
    """
    south, north, west, east = await _get_city_bbox(city)

    query = f"""
    [out:json][timeout:25];
    (
      node["tourism"="attraction"]({south},{west},{north},{east});
      node["tourism"="museum"]({south},{west},{north},{east});
      node["tourism"="viewpoint"]({south},{west},{north},{east});
      node["historic"]({south},{west},{north},{east});
    );
    out body {limit};
    """

    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        response = await client.post(OVERPASS_URL, data={"data": query})
        response.raise_for_status()
        data = response.json()

    elements = data.get("elements", [])
    if not elements:
        return f"No attractions found for {city}."

    lines = [f"Attractions in {city}:"]
    for el in elements[:limit]:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:en")
        if not name:
            continue
        kind = tags.get("tourism") or tags.get("historic") or "attraction"
        lines.append(f"- {name} ({kind})")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="sse")
