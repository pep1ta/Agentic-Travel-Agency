# Run with: uv run python -m agents.hotel

import asyncio
import logging

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.routing import Route

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import TransportProtocol

from agents.hotel.agent import HotelAgent
from agents.hotel.executor import HotelExecutor

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HOST = "0.0.0.0"
PORT = 10003
PUBLIC_URL = f"http://localhost:{PORT}"

# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="hotel_booking",
        name="Hotel Booking",
        description=(
            "Searches for available hotels in a city and handles the full booking flow "
            "including check-in/check-out dates, booking confirmation and invoice."
        ),
        tags=["hotel", "booking", "travel"],
        examples=["Book a hotel in Rome", "Find hotels in Berlin"],
    )
    return AgentCard(
        name="Hotel Agent",
        description="Handles hotel search and booking for the travel agency.",
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
    """Builds and returns the Starlette app with all routes and components wired together."""
    agent = HotelAgent()
    executor = HotelExecutor(agent=agent)
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
    logger.info(f"Hotel Agent starting at http://{HOST}:{PORT}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())