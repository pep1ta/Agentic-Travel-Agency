# Run with: uv run python -m agents.business_travel

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

from agents.business_travel.agent import BusinessTravelAgent
from agents.business_travel.executor import BusinessTravelExecutor

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HOST = "0.0.0.0"
PORT = 10004
PUBLIC_URL = f"http://localhost:{PORT}"

# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="business_travel_planning",
        name="Business Travel Planning",
        description=(
            "Plans business travel options and delegates the final "
            "policy-compliant selection to the SmartContractClient."
        ),
        tags=["business-travel", "policy", "smart-contract"],
        examples=["I need to be in Munich on Monday at 10:00."],
    )
    return AgentCard(
        name="Business Travel Agent",
        description=(
            "Plans business travel options and delegates the final "
            "policy-compliant selection to the SmartContractClient."
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
    """Builds and returns the Starlette app with all routes wired together."""
    agent = BusinessTravelAgent()
    executor = BusinessTravelExecutor(agent=agent)
    agent_card = build_agent_card()
    task_store = InMemoryTaskStore()

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        agent_card=agent_card,
    )

    routes: list[Route] = [
        *create_agent_card_routes(agent_card),  # GET /.well-known/agent-card.json
        *create_jsonrpc_routes(request_handler, rpc_url="/"),  # POST /
    ]

    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    app = await build_app()
    config = uvicorn.Config(app=app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Business Travel Agent starting at http://{HOST}:{PORT}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
