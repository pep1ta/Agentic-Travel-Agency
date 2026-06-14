# agents/host/orchestrator.py

import json
import logging
import uuid
from typing import Any

import httpx
from openai import AsyncOpenAI

from a2a.client import ClientFactory, ClientConfig
from a2a.types import TaskState, Message, Part, Role, SendMessageRequest, AgentInterface

from utilities.blockchain.business_agent_registry_discovery import (
    discover_business_travel_agent_endpoint,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class OrchestratorAgent:
    """Core orchestrator logic.

    Receives agent cards and builds A2A connectors from them.
    Uses OpenAI directly to decide which A2A agent to call.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        """Synchronous setup — declares all instance attributes.
        Network calls are deferred to initialize() because __init__ cannot be async.
        """
        self._openai = AsyncOpenAI()  # reads OPENAI_API_KEY from env
        # 120s timeout: BTA delegation involves OpenAI + 3 provider A2A calls + SmartContractClient
        self._factory = ClientFactory(ClientConfig(httpx_client=httpx.AsyncClient(timeout=120.0)))
        self._active_agent: dict[str, str] = {}  # context_id → agent_name when INPUT_REQUIRED
        self._last_agent: dict[str, str] = {}  # context_id -> last delegated agent
        self._last_business_travel_context_id: str | None = None
        
        self._agent_clients: dict[str, Any] = {} 
        self._tools: list[dict] = []


    async def initialize(self, agent_urls: list[str]) -> None:
        """Async setup — must be called once before invoke().
        Builds A2A clients for all sub-agents.
        """
        # 1. Build the small OpenAI tool list for A2A routing.
        self._tools = self._build_tools()
        logger.info("OpenAI tool names: %s", [t["function"]["name"] for t in self._tools])

        # 2. Optional on-chain discovery for the BusinessTravelAgent.
        # If this read-only lookup fails, the local JSON registry remains the
        # simple fallback for the demo.
        discovered_endpoint, discovery_error = discover_business_travel_agent_endpoint()

        if discovered_endpoint:
            logger.info(f"Using on-chain discovered BusinessTravelAgent: {discovered_endpoint}")
            agent_urls = [
                url for url in agent_urls
                if "10004" not in url and "Business Travel Agent" not in url
            ]
            agent_urls.insert(0, discovered_endpoint)
        else:
            logger.info("Using local JSON fallback for BusinessTravelAgent")
            if discovery_error:
                logger.info(f"On-chain BusinessTravelAgent discovery skipped: {discovery_error}")

        # 3. Build A2A clients for each sub-agent based on the discovered/fallback URLs
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

    def _build_tools(self) -> list[dict]:
        """Builds the OpenAI tool definition list for A2A routing only."""
        return [
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

    # -----------------------------------------------------------------------
    # System prompt
    # -----------------------------------------------------------------------

    def _root_instruction(self) -> str:
        return (
            "You are the orchestrator of an enterprise agent system. "
            "The company operates specialized agents for different task domains. "
            "Your job is to route user requests to the appropriate specialized agent, "
            "not to solve domain-specific tasks yourself.\n\n"
            "Use list_agents() to inspect the available agents. "
            "Use delegate_task(agent_name, message) to delegate the user's original request "
            "to the selected agent. Preserve the user's original wording as much as possible.\n\n"
            "For business travel or business travel planning requests, delegate to the "
            "\"Business Travel Agent\". The Business Travel Agent is responsible for "
            "collecting and structuring rail, flight and mobility options. The final "
            "policy-compliant travel selection is made by the SmartContractClient, "
            "not by you and not by the LLM.\n\n"
            "Do not ask your own travel slot-filling questions. "
            "Do not ask whether the user prefers train or flight. "
            "Do not interpret cities, dates, times, routes or request completeness yourself. "
            "Do not choose the final travel option yourself. "
            "If a short confirmation or booking request refers to a previous business travel "
            "decision, delegate it to the Business Travel Agent in the appropriate context.\n\n"
            "Always choose the appropriate specialized agent based on the available agent list "
            "and return the delegated agent's result to the user."
        )

    def _routing_context_note(self, context_id: str | None) -> str:
        """Builds non-semantic routing context for the LLM tool router."""
        last_agent = self._last_agent.get(context_id) if context_id else None
        has_business_travel_context = self._last_business_travel_context_id is not None

        return (
            "Routing context:\n"
            f"- current_context_id: {context_id or '(none)'}\n"
            f"- last_agent_for_current_context: {last_agent or '(none)'}\n"
            f"- has_previous_business_travel_context: {has_business_travel_context}\n"
            "Use this only to choose the right tool or sub-agent. Do not infer "
            "travel slots in the orchestrator."
        )

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
                if context_id:
                    self._last_agent[context_id] = agent_name
                    if agent_name == "Business Travel Agent":
                        self._last_business_travel_context_id = context_id
        return "\n".join(response_parts) if response_parts else "(no response)"


    # -----------------------------------------------------------------------
    # Main invoke loop
    # -----------------------------------------------------------------------

    async def invoke(self, query: str, context_id: str | None = None) -> tuple[str, bool]:
        """Processes a user message using OpenAI with tool use."""

        # If a sub-agent is waiting for input, delegate directly without calling OpenAI
        if context_id and context_id in self._active_agent:
            agent_name = self._active_agent[context_id]
            result = await self._delegate_task(agent_name, query, context_id)
            input_required = context_id in self._active_agent
            return result, input_required

        messages = [
            {"role": "system", "content": self._root_instruction()},
            {"role": "system", "content": self._routing_context_note(context_id)},
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
                    delegate_context_id = context_id
                    if args["agent_name"] == "Business Travel Agent":
                        if (
                            context_id
                            and self._last_agent.get(context_id) == "Business Travel Agent"
                        ):
                            delegate_context_id = context_id
                        elif self._last_business_travel_context_id:
                            logger.info(
                                "Routing BusinessTravelAgent delegation to previous business travel context"
                            )
                            delegate_context_id = self._last_business_travel_context_id

                    result = await self._delegate_task(
                        args["agent_name"],
                        args["message"],
                        delegate_context_id,
                    )
                    if delegate_context_id and delegate_context_id in self._active_agent:
                        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
                        return result, True
                    # Pass the delegate result directly — no second LLM call that would
                    # summarize away alternatives, rejected options, and policy details.
                    logger.info(f"Tool result for delegate_task (pass-through): {result[:200]}")
                    return result, False
                else:
                    result = f"Unknown tool: {name}"

                logger.info(f"Tool result for {name}: {result[:200]}")
                # Append tool result to history so OpenAI can use it in the next iteration
                messages.append({ "role": "tool", "tool_call_id": tool_call.id, "content": result})
