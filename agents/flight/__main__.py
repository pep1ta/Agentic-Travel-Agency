# Run with: uv run python -m agents.flight

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

from agents.flight.agent import FlightProviderAgent
from agents.flight.executor import FlightProviderExecutor

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HOST = "0.0.0.0"
PORT = 10011
PUBLIC_URL = f"http://localhost:{PORT}"


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="flight_travel_search",
        name="Flight Travel Search",
        description=(
            "Returns mock flight offers for a business trip. "
            "Input: JSON with origin, destination, appointment_time. "
            "Output: JSON list of flight offers (mode='flight'). "
            "Transfer enrichment is handled separately by the MobilityProviderAgent."
        ),
        tags=["flight", "business-travel", "provider"],
        examples=[
            '{"origin": "Dortmund", "destination": "Wien", "appointment_time": "Montag um 10 uhr"}',
            '{"action": "book", "offer_id": "flight-1"}',
        ],
    )
    return AgentCard(
        name="Flight Provider Agent",
        description=(
            "Provider agent for flight offers. Wraps mcp_servers/flight_server.py "
            "behind an A2A interface. Registered with capability 'flight' in the "
            "BusinessAgentRegistry."
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


async def build_app() -> Starlette:
    agent = FlightProviderAgent()
    executor = FlightProviderExecutor(agent=agent)
    agent_card = build_agent_card()
    task_store = InMemoryTaskStore()

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=agent_card,
    )

    routes: list[Route] = [
        *create_agent_card_routes(agent_card),
        *create_jsonrpc_routes(request_handler, rpc_url="/"),
    ]

    return Starlette(routes=routes)


async def main() -> None:
    app = await build_app()
    config = uvicorn.Config(app=app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Flight Provider Agent starting at http://{HOST}:{PORT}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
