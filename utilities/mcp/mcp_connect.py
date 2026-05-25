# utilities/mcp/mcp_connect.py

import asyncio
import logging

from distro import name
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client

from utilities.mcp.mcp_discovery import MCPDiscovery

load_dotenv()
logger = logging.getLogger(__name__)


class MCPTool:
    """Represents a single MCP tool that can be called on a remote MCP server via SSE."""

    def __init__(self, name: str, description: str, input_schema: dict, url: str):
        self.name = name
        self.description = description
        self.input_schema = input_schema  # used to build the OpenAI tool definition 
        self._url = url                   # SSE endpoint of the MCP server that provides this tool

    async def run(self, args: dict) -> str:
        """Connects to the MCP server, calls the tool with the given args, and returns the result.
        
        A new SSE connection is opened for each call — MCP SSE sessions are not persistent.
        """
        async with sse_client(self._url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool(self.name, args)

                content = getattr(response, "content", None)
                if content:
                    return str(content[0].text if hasattr(content[0], "text") else content)
                return str(response)


class MCPConnector:
    """Discovers MCP servers from config and loads their tools into MCPTool objects."""

    def __init__(self, config_file: str = None):
        self.discovery = MCPDiscovery(config_file=config_file)
        self.tools: list[MCPTool] = []


    async def initialize(self) -> None:
        """Connects to each configured MCP server via SSE and fetches its tool list.
        
        For each tool found, creates an MCPTool object that stores the server URL
        so the tool can be called later without keeping the connection open.
        """
        servers = self.discovery.list_servers()

        for name, info in servers.items():
            url = info.get("url")

            try:
                async with sse_client(url) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()

                        tool_list = (await session.list_tools()).tools # fetch available tools
                        for t in tool_list:
                            self.tools.append(MCPTool( 
                                name=t.name,
                                description=t.description,
                                input_schema=t.inputSchema,
                                url=url  # stored so MCPTool.run() knows where to connect
                            ))
                            logger.info(f"Loaded MCP tool: {t.name} from {name}")

            except Exception as e:
                logger.warning(f"Failed to load tools from MCP server {name}: {e}", exc_info=True)

    def get_tools(self) -> list[MCPTool]:
        return self.tools.copy()