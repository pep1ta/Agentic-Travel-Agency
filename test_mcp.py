# test_mcp_sse.py
import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def test():
    async with sse_client("http://localhost:8001/sse") as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Tools: {tools}")

asyncio.run(test())