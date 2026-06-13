# agents/host/orchestrator.py

import json
import logging
import unicodedata
import uuid
from typing import Any

from openai import AsyncOpenAI

from a2a.client import ClientFactory
from a2a.types import TaskState, Message, Part, Role, SendMessageRequest, AgentInterface

from utilities.mcp.mcp_connect import MCPConnector, MCPTool

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class OrchestratorAgent:
    """Core orchestrator logic.

    Receives agent cards and builds A2A connectors from them.
    Instantiates MCPConnector to load MCP tools.
    Uses OpenAI directly to decide which tool/agent to call.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        """Synchronous setup — declares all instance attributes.
        Network calls are deferred to initialize() because __init__ cannot be async.
        """
        self._openai = AsyncOpenAI()  # reads OPENAI_API_KEY from env
        self._factory = ClientFactory() # A2A client factory for building clients to sub-agents based on their cards
        self._active_agent: dict[str, str] = {}  # context_id → agent_name when INPUT_REQUIRED
        
        self._agent_clients: dict[str, Any] = {} 
        self._mcp_tools: dict[str, MCPTool] = {}
        self._tools: list[dict] = []


    async def initialize(self, agent_urls: list[str]) -> None:
        """Async setup — must be called once before invoke().
        Connects to MCP servers to load tools and builds A2A clients for all sub-agents.
        """
        # 1. Connect to each MCP server and fetch available tools
        self.mcp = MCPConnector()
        await self.mcp.initialize()
        mcp_tools = self.mcp.get_tools()
        self._mcp_tools = {t.name: t for t in mcp_tools} # name → MCPTool for calling later
        self._tools = self._build_tools(mcp_tools) # convert to OpenAI tool definitions
        logger.info(f"Retrieved MCP tools: {[t.name for t in mcp_tools]}")

        # 2. Build A2A clients for each sub-agent based on the URLs in the registry file
        for url in agent_urls:
            try:
                client = await self._factory.create_from_url(url)
                name = client._card.name
                self._agent_clients[name] = client
                logger.info(f"Built A2A client for: {name} at {url}")
            except Exception as e:
                logger.warning(f"Failed to build client for {url}: {e}")


    # -----------------------------------------------------------------------
    # Tool definitions for OpenAI
    # -----------------------------------------------------------------------

    def _build_tools(self, mcp_tools: list[MCPTool]) -> list[dict]:
        """Builds the full OpenAI tool definition list."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "list_agents",
                    "description": "Lists all available A2A sub-agents by name.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delegate_task",
                    "description": "Delegates a task to a named A2A sub-agent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "agent_name": {
                                "type": "string",
                                "description": "The name of the agent to delegate to.",
                            },
                            "message": {
                                "type": "string",
                                "description": "The message or task to send to the agent.",
                            },
                        },
                        "required": ["agent_name", "message"],
                    },
                },
            },
        ]

        for tool in mcp_tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            })

        return tools

    # -----------------------------------------------------------------------
    # System prompt
    # -----------------------------------------------------------------------

    def _root_instruction(self) -> str:
        return (
            "You are a travel agency orchestrator. You route user requests to the right tools or sub-agents.\n"
            "For business travel requests, use list_agents() and then delegate_task() to the "
            "\"Business Travel Agent\".\n"
            "The Business Travel Agent collects and structures rail, flight and mobility options.\n"
            "The final policy-compliant travel selection is made by the SmartContractClient, "
            "not by you, not by the LLM, and not by the agent.\n"
            "Do not choose the final travel option yourself. Explain the result returned by the delegated agent.\n\n"
            "You help users by:\n"
            "1. Using list_agents() to see available sub-agents.\n"
            "2. Using delegate_task(agent_name, message) to delegate business travel planning "
            "   to the Business Travel Agent.\n"
            "3. Using delegate_task(agent_name, message) to delegate hotel searches and bookings "
            "   to the Hotel Agent when the user asks for hotel booking.\n"
            "4. Using MCP tools to fetch weather and attractions data when relevant.\n"
            "Always pick the right tool for the job and respond helpfully."
        )

    def _normalize_text(self, text: str) -> str:
        """Normalizes German umlauts for small routing heuristics."""
        text = text.lower()
        text = (
            text.replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
            .replace("ã¼", "ue").replace("ã¤", "ae").replace("ã¶", "oe")
        )
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

    def _looks_like_business_travel_request(self, query: str) -> bool:
        """Detects simple business travel requests before calling the LLM.

        This keeps A2A multi-turn slot filling with the BusinessTravelAgent
        reliable. The BusinessTravelAgent remains responsible for collecting
        and structuring travel options.
        """
        query_normalized = self._normalize_text(query)
        has_travel_time = "montag" in query_normalized or "10 uhr" in query_normalized
        has_known_destination = (
            "muenchen" in query_normalized
            or "wien" in query_normalized
            or "vienna" in query_normalized
        )
        has_route_word = (
            " von " in f" {query_normalized} "
            or " nach " in f" {query_normalized} "
            or " in " in f" {query_normalized} "
        )
        return has_travel_time and has_known_destination and has_route_word

    # -----------------------------------------------------------------------
    # Tool implementations
    # -----------------------------------------------------------------------

    def _list_agents(self) -> str:
        return json.dumps(list(self._agent_clients.keys()))

    async def _delegate_task(self, agent_name: str, message: str,  context_id: str | None = None) -> str:
        if agent_name not in self._agent_clients:
            return f"Unknown agent: {agent_name}. Available: {list(self._agent_clients.keys())}"

        client = self._agent_clients[agent_name]
        request = SendMessageRequest(message=Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=message)], context_id=context_id or "")) # Wrap the message in an A2A Message object with a unique ID

        response_parts = []
        last_result = None
        # Send request to the sub-agent via the A2A SDK client. 
        async for result in client.send_message(request):
            last_result = result
            field = result.WhichOneof("payload")  # returns which of the four payload fields is set
            if field == "message":  # Direct message response — text is in message.parts
                for part in result.message.parts:
                    if getattr(part, "text", None):
                        response_parts.append(part.text)
            elif field == "task":  # Task response — text is nested in task.status.message.parts
                if result.task.status.HasField("message"):
                    for part in result.task.status.message.parts:
                        if getattr(part, "text", None):
                            response_parts.append(part.text)
        # Track if sub-agent is waiting for input so next turn goes directly to it
        if last_result and last_result.WhichOneof("payload") == "task":
            state = last_result.task.status.state
            if state == TaskState.TASK_STATE_INPUT_REQUIRED:
                if context_id:
                    self._active_agent[context_id] = agent_name
            else:
                self._active_agent.pop(context_id, None)
        return "\n".join(response_parts) if response_parts else "(no response)"


    async def _call_mcp_tool(self, tool_name: str, args: dict) -> str:
        tool = self._mcp_tools.get(tool_name)
        if not tool:
            return f"Unknown MCP tool: {tool_name}"
        try:
            return await tool.run(args)
        except Exception as e:
            logger.error(f"MCP tool call failed for {tool_name}: {e}")
            return f"Error calling {tool_name}: {e}"


    # -----------------------------------------------------------------------
    # Main invoke loop
    # -----------------------------------------------------------------------

    async def invoke(self, query: str, context_id: str | None = None) -> tuple[str, bool]:
        """Processes a user message using OpenAI with tool use."""
        print(f"DEBUG invoke: context_id={context_id}, active_agents={self._active_agent}")

        # If a sub-agent is waiting for input, delegate directly without calling OpenAI
        if context_id and context_id in self._active_agent:
            agent_name = self._active_agent[context_id]
            result = await self._delegate_task(agent_name, query, context_id)
            input_required = context_id in self._active_agent
            return result, input_required

        # Business travel requests are delegated deterministically so the
        # BusinessTravelAgent can use A2A INPUT_REQUIRED for missing slots.
        if self._looks_like_business_travel_request(query):
            result = await self._delegate_task("Business Travel Agent", query, context_id)
            input_required = bool(context_id and context_id in self._active_agent)
            return result, input_required

        messages = [
            {"role": "system", "content": self._root_instruction()},
            {"role": "user", "content": query},
        ]

        while True:
            # Call OpenAI with the current message history and the available tool definitions.
            # OpenAI reads the tool descriptions and decides which tool to call based on the user query.
            # tool_choice="auto" lets OpenAI decide whether to call a tool or respond directly.
            response = await self._openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=self._tools,
                tool_choice="auto",
            )

            choice = response.choices[0]
            messages.append(choice.message.model_dump(exclude_none=True)) # add assistant response to history
            
            # No tool calls means OpenAI has enough information to answer directly
            if not choice.message.tool_calls:
                return choice.message.content or "", False
            
            # OpenAI requested one or more tool calls — execute each and append results to history.
            # On the next iteration, OpenAI will see the results and decide whether to call
            # another tool or produce a final answer.
            for tool_call in choice.message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                logger.info(f"Tool call: {name}({args})")

                if name == "list_agents":
                    result = self._list_agents()
                elif name == "delegate_task":
                    result = await self._delegate_task(args["agent_name"], args["message"], context_id)
                    if context_id and context_id in self._active_agent:
                        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
                        return result, True
                else:
                    # Any other tool name is an MCP tool (e.g. get_weather, get_attractions)
                    result = await self._call_mcp_tool(name, args)

                logger.info(f"Tool result for {name}: {result[:200]}")
                # Append tool result to history so OpenAI can use it in the next iteration
                messages.append({ "role": "tool", "tool_call_id": tool_call.id, "content": result})
