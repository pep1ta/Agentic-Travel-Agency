# Travel Agency — Multi-Agent System

A multi-agent travel planning system built with the A2A SDK and MCP protocol. No LLM frameworks (no LangChain, no Google ADK) — direct OpenAI API and raw SDK usage.

## Architecture

```
User (CMD)
    ↓
Customer Agent          (Port 10000)   — Entry point, forwards user messages
    ↓
Orchestrator Agent      (Port 10002)   — OpenAI LLM, decides which tool/agent to call
    ↙                ↘
Hotel Agent             MCP Tools
(Port 10003)            - Weather Server     (Port 8001)
                        - Attractions Server  (Port 8002)
```

The Hotel Agent has its own dedicated MCP server for hotel data:
```
Hotel Agent (Port 10003)
    ↓
Hotel MCP Server (Port 8003) — mock hotel data, search and booking
```

## Stack

- **A2A SDK** (`a2a-sdk>=1.0.3`) — Agent-to-Agent communication
- **MCP SDK** (`mcp`) — Model Context Protocol for tool access
- **OpenAI** (`openai`) — LLM for the Orchestrator
- **FastAPI / Starlette / Uvicorn** — A2A server infrastructure
- **httpx** — HTTP client for external APIs

## Project Structure

```
travel_agency/
├── agents/
│   ├── orchestrator/
│   │   ├── agent.py        # OrchestratorAgent — OpenAI + MCP + A2A delegation
│   │   ├── executor.py     # OrchestratorExecutor — AgentExecutor adapter
│   │   └── __main__.py     # Entry point, Port 10002
│   ├── customer/
│   │   ├── agent.py        # CustomerAgent — thin pass-through to Orchestrator
│   │   ├── executor.py     # CustomerExecutor — AgentExecutor adapter
│   │   └── __main__.py     # Entry point, Port 10000
│   └── hotel/
│       ├── agent.py        # HotelAgent — multi-turn booking logic, calls Hotel MCP Server
│       ├── executor.py     # HotelExecutor — AgentExecutor adapter with INPUT_REQUIRED support
│       └── __main__.py     # Entry point, Port 10003
├── mcp_servers/
│   ├── weather_server.py     # Weather via wttr.in, SSE Transport, Port 8001
│   ├── attractions_server.py # Attractions via Overpass API, SSE Transport, Port 8002
│   └── hotel_server.py       # Mock hotel data, SSE Transport, Port 8003
├── app/
│   └── cmd/
│       └── cmd.py          # CLI client
├── utilities/
│   └── mcp/
│       ├── mcp_connect.py      # MCPConnector — loads tools from MCP servers
│       ├── mcp_discovery.py    # MCPDiscovery — reads mcp_config.json
│       └── mcp_config.json     # MCP server URLs for the Orchestrator
└── utilities/
    └── a2a/
        └── agent_registry.json # A2A sub-agent URLs for the Orchestrator
```

## Setup

```bash
# Install dependencies
uv sync

# Create .env file
echo "OPENAI_API_KEY=your_key_here" > .env
```

## Starting the System

Start each component in a separate terminal, in this order:

**1. Weather MCP Server**
```bash
uv run python mcp_servers/weather_server.py
# Runs on http://localhost:8001
```

**2. Attractions MCP Server**
```bash
uv run python mcp_servers/attractions_server.py
# Runs on http://localhost:8002
```

**3. Hotel MCP Server**
```bash
uv run python mcp_servers/hotel_server.py
# Runs on http://localhost:8003
```

**4. Hotel Agent**
```bash
uv run python -m agents.hotel
# Runs on http://localhost:10003
```

**5. Orchestrator Agent**
```bash
uv run python -m agents.orchestrator
# Runs on http://localhost:10002
```

**6. Customer Agent**
```bash
uv run python -m agents.customer
# Runs on http://localhost:10000
```

**7. CMD Client**
```bash
uv run python app/cmd/cmd.py --agent http://localhost:10000

# Options:
# --agent    Base URL of the A2A agent (default: http://localhost:10000)
```

## Configuration

**`utilities/mcp/mcp_config.json`** — MCP server endpoints for the Orchestrator:
```json
{
    "mcpServers": {
        "weather": { "url": "http://localhost:8001/sse" },
        "attractions": { "url": "http://localhost:8002/sse" }
    }
}
```

Note: The Hotel MCP Server (`http://localhost:8003`) is not in this config — it is called directly by the Hotel Agent, not by the Orchestrator.

**`utilities/a2a/agent_registry.json`** — A2A sub-agent URLs for the Orchestrator:
```json
[
    "http://localhost:10003"
]
```

## Example Usage

**Weather and attractions:**
```
You: What is the weather in Rome?
Agent: The weather in Rome is sunny with a temperature of 29°C.

You: What can I do in Rome?
Agent: Here are some attractions in Rome:
- Quattro Fontane (attraction)
- Catacombe di Priscilla (attraction)
- Fontana dell'Acqua Acetosa (attraction)
```

**Hotel booking (multi-turn):**
```
You: Book a hotel in Rome
Agent: Available hotels in Rome:
- Budget Inn (budget) — $60/night
- City Hotel (mid) — $120/night
- Grand Palace (luxury) — $280/night
Which hotel would you like to book?

Agent is waiting for input. Please enter your response: City Hotel
Agent: What is your check-in date? (format: YYYY-MM-DD)

Agent is waiting for input. Please enter your response: 2026-06-24
Agent: What is your check-out date? (format: YYYY-MM-DD)

Agent is waiting for input. Please enter your response: 2026-06-28
Agent: Booking summary:
  Hotel:     City Hotel
  City:      Rome
  Check-in:  2026-06-24
  Check-out: 2026-06-28
Would you like to confirm this booking? (yes/no)

Agent is waiting for input. Please enter your response: yes
Agent: Booking Confirmation
====================
Hotel:    City Hotel (mid)
City:     Rome
Check-in: 2026-06-24
Check-out:2026-06-28
Nights:   4

Invoice
=======
$120/night x 4 nights = $480
Total due: $480
```
