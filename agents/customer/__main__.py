# Run with: uv run python -m agents.customer

import asyncio
import logging

import httpx
import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.routing import Route

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import TransportProtocol
from a2a.client import ClientFactory, ClientConfig

from agents.customer.agent import CustomerAgent
from agents.customer.executor import CustomerExecutor

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HOST = "0.0.0.0"
PORT = 10000
PUBLIC_URL = f"http://localhost:{PORT}"
ORCHESTRATOR_URL = "http://localhost:10002"


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

def build_agent_card() -> AgentCard:
    """Describes this agent to the outside world — name, skills, capabilities and URL."""
    skill = AgentSkill(
        id="customer_travel",
        name="Travel Assistant",
        description="Helps users plan trips by connecting them to the travel agency system.",
        tags=["travel", "customer"],
        examples=["I want to visit Rome", "Find me a hotel in Berlin"],
    )
    return AgentCard(
        name="Travel Customer Agent",
        description="Customer-facing agent for the digital travel agency.",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
        default_input_modes=["text"],
        default_output_modes=["text"],
        supported_interfaces=[AgentInterface(
            url=PUBLIC_URL,  
            protocol_binding=TransportProtocol.JSONRPC,
        )],
    )

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

async def build_app() -> Starlette:
    """Build A2A client for the orchestrator — fetches its agent card and sets up the connection"""
    config = ClientConfig(httpx_client=httpx.AsyncClient(timeout=120))
    client = await ClientFactory(config=config).create_from_url(ORCHESTRATOR_URL) # Fetch the orchestrator's agent card and create an A2A client to send requests to it

    customer = CustomerAgent(client=client) # The customer agent uses this client to forward incoming user messages to the orchestrator
    executor = CustomerExecutor(agent=customer) # Wraps the customer agent so the A2A server knows how to call it when a request arrives
    agent_card = build_agent_card()
    task_store = InMemoryTaskStore() 

    request_handler = DefaultRequestHandler( # Processes incoming JSON-RPC requests from remote agents
        agent_executor=executor, # The executor that contains the agent logic to run on each request
        task_store=task_store, # In-memory store that tracks task state across multiple requests (e.g. INPUT_REQUIRED follow-ups)
        agent_card=agent_card, # Used for capability checks (e.g. streaming, push notifications) before allowing certain endpoints
    )

    routes: list[Route] = [
        *create_agent_card_routes(agent_card), # GET /.well-known/agent-card.json
        *create_jsonrpc_routes(request_handler, rpc_url="/"), # POST / for incoming A2A requests
    ]

    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    app = await build_app()
    config = uvicorn.Config(app=app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Customer Agent starting at http://{HOST}:{PORT}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())