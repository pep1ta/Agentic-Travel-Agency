# Run with: uv run python -m agents.host

import asyncio
import json
import logging
import os

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.routing import Route

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, AgentInterface
from a2a.utils.constants import TransportProtocol
from a2a.client import A2ACardResolver

from agents.orchestrator.agent import OrchestratorAgent
from agents.orchestrator.executor import OrchestratorExecutor

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HOST = "0.0.0.0"
PORT = 10002
PUBLIC_URL = f"http://localhost:{PORT}" 


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="orchestrate_travel",
        name="Travel Orchestrator",
        description=(
            "Orchestrates travel planning by delegating business travel requests "
            "to the Business Travel Agent and hotel bookings to the Hotel Agent."
        ),
        tags=["travel", "orchestrator"],
        examples=[
            "I need to be in Munich on Monday at 10:00.",
            "Find hotels in Berlin",
        ],
    )

    return AgentCard(
        name="Enterprise Orchestrator",
        description=(
            "Orchestrates enterprise agent coordination. "
            "Delegates business travel requests to BusinessTravelAgent; final policy selection is enforced by the on-chain BusinessTravelPolicy contract."
        ),
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
    """Initializes all components and builds the Starlette app.
    
    Loads sub-agent cards from the registry, initializes the OrchestratorAgent
    (which builds A2A clients and loads MCP tools), then wires everything together
    into a Starlette app with A2A-compliant routes.
    """
    bta_url = os.environ.get("BUSINESS_TRAVEL_AGENT_URL", "").strip()
    if bta_url:
        agent_urls: list[str] = [bta_url]
        logger.info(f"BusinessTravelAgent URL from BUSINESS_TRAVEL_AGENT_URL: {bta_url}")
    else:
        registry_path = os.path.join("utilities", "a2a", "agent_registry.json")
        with open(registry_path) as f:
            agent_urls: list[str] = json.load(f)

    orchestrator = OrchestratorAgent() # Initialize the orchestrator with the loaded agent cards
    await orchestrator.initialize(agent_urls=agent_urls) # Build A2A clients for sub-agents and load MCP tools during initialization

    executor = OrchestratorExecutor(agent=orchestrator)
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
    logger.info(f"Orchestrator starting at http://{HOST}:{PORT}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
