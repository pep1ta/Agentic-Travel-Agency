# Run with: uv run python app/cmd/cmd.py --agent http://localhost:10002

import asyncio
import json
from typing import Any
from uuid import uuid4

import click
import httpx
from rich import print as rprint
from rich.syntax import Syntax

from a2a.client import ClientFactory, ClientConfig
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_message(text: str, task_id: str | None = None, context_id: str | None = None) -> Message:
    """Builds a Message object from user input text.
    Optionally includes task_id and context_id for multi-turn agent interactions.
    """
    message = Message(message_id=uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=text)])

    if context_id:
        message.context_id = context_id
    if task_id:
        message.task_id = task_id

    return message


def print_json_response(response: Any, title: str) -> None:
    """Nicely prints JSON responses from the agent.
    Special handling for Message objects to display agent text more cleanly.
    """
    print(f"\n--- {title} ---")

    if hasattr(response, "WhichOneof"):
        field = response.WhichOneof("payload")
        if field == "message":
            for part in response.message.parts:
                if getattr(part, "text", None):
                    rprint(f"Agent: {part.text}")
            return
        elif field == "task":
            if response.task.status.HasField("message"):
                for part in response.task.status.message.parts:
                    if getattr(part, "text", None):
                        rprint(f"Agent: {part.text}")
            return

    # Task with Status Message
    task = extract_task(response)
    if task:
        status_msg = getattr(task.status, "message", None)
        if status_msg:
            for part in status_msg.parts:
                if getattr(part, "text", None):
                    rprint(f"Agent: {part.text}")
            return
        
    # If the response is not a Message object, attempt to serialize it as JSON for pretty printing.
    try:  
        if hasattr(response, "to_dict"):
            data = response.to_dict()
        elif hasattr(response, "model_dump"):
            data = response.model_dump(mode="json", exclude_none=True)
        elif hasattr(response, "root") and hasattr(response.root, "model_dump"):
            data = response.root.model_dump(mode="json", exclude_none=True)
        else:
            data = str(response)

        json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
        rprint(syntax)

    except Exception as e:
        rprint(f"Error printing JSON response: {e}")
        rprint(repr(response))


def extract_task(result: Any):
    """Extracts the task object from an agent response.
    Checks multiple possible locations where the task might be stored.
    """
    return (getattr(result, "task", None) or getattr(result, "result", None) or getattr(getattr(result, "root", None), "result", None))



# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def handle_non_streaming(client, text: str, task_id: str | None = None, context_id: str | None = None) -> None:
    """Sends a message and waits for a single response.
    Checks if further input is required from the user (INPUT_REQUIRED state).
    """
    request = SendMessageRequest(message=build_message(text, task_id, context_id))
    last_task = None

    async for result in client.send_message(request):
        print_json_response(result, "Agent Reply")  
        task = extract_task(result)
        if task:
            last_task = task

    if last_task:
        print(f"DEBUG last_task context_id: {getattr(last_task, 'context_id', None)}")
        print(f"DEBUG last_task state: {getattr(last_task.status, 'state', None)}")
        
        if getattr(last_task.status, "state", None) == TaskState.TASK_STATE_INPUT_REQUIRED: # Check if the last task indicates that the agent is waiting for more input from the user
            follow_up = input("Agent is waiting for input. Please enter your response: ")
            await handle_non_streaming(client, follow_up, task_id=getattr(task, "id", None), context_id=getattr(task, "context_id", None)) # Recursively call the non-streaming handler with the follow-up message


async def handle_streaming(client, text: str, task_id: str | None = None, context_id: str | None = None) -> None:
    """Continuously listens for streaming updates from the agent.
    Checks if further input is required after the stream ends.
    """
    request = SendMessageRequest(message=build_message(text, task_id, context_id))
    latest_task_id = task_id
    latest_context_id = context_id
    input_required = False
    last_task = None

    async for update in client.subscribe(request): # Listen for streaming updates from the agent in response to the initial message
        print_json_response(update, "Streaming Update") # Print each update from the agent as it arrives, which may include intermediate responses or status updates
        task = extract_task(update) # Extract the task from the update 

        if not task:
            continue

        last_task = task
        latest_task_id = getattr(task, "id", latest_task_id)
        latest_context_id = getattr(task, "context_id", latest_context_id)

        if getattr(task.status, "state", None) == TaskState.TASK_STATE_INPUT_REQUIRED: # Check if the task status indicates that the agent is waiting for more input from the user
            input_required = True

    if input_required: # After the streaming updates have finished, if we detected that the agent is waiting for input, prompt the user for a follow-up message
        follow_up = input("Agent is waiting for input. Please enter your response: ")
        await handle_streaming(client, follow_up, latest_task_id, latest_context_id) # If further input is required, recursively call the streaming handler to send the follow-up message and continue listening for updates


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

async def interactive_loop(client, supports_streaming: bool) -> None:
    """Continuously sends messages to the agent until the user types 'exit'."""
    print("\nWelcome to our digital Travel Agency! Type your messages below (type 'exit' to quit):")

    while True:
        query = input("You: ").strip() # Get user input and remove leading/trailing whitespace

        if query.lower() == "exit":
            print("Goodbye!") # Exit the loop and end the program
            break

        if not query:
            continue

        if supports_streaming:
            await handle_streaming(client, query) # If the agent supports streaming, use the streaming handler to send the message and receive updates
        else:
           await handle_non_streaming(client, query) # If the agent does not support streaming, use the non-streaming handler to send the message and wait for a single response



# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_main(agent_url: str) -> None:
    print(f"Connecting to agent at: {agent_url}")

    try:
        factory = ClientFactory(config=ClientConfig(httpx_client=httpx.AsyncClient(timeout=120))) # Create a client factory instance
        customer_agent_client = await factory.create_from_url(agent_url) # Creates Agent based by URL

        async with httpx.AsyncClient(timeout=60) as session: # Create an HTTP client to fetch the agent card
            res = await session.get(f"{agent_url}/.well-known/agent-card.json") #
            res.raise_for_status() # Ensure we got a successful response otherwise raise an error
            agent_card = res.json() # Parse the agent card JSON

        agent_name = agent_card.get("name", "Unknown Agent") # Get the agent's name from the card, default to "Unknown Agent" if not provided
        supports_streaming = agent_card.get("capabilities", {}).get("streaming", False) # Check if the agent supports streaming from its capabilities

        print(
            f"Connected to agent: {agent_name} "
            f"(Streaming support: {'Yes' if supports_streaming else 'No'})"
        )

        await interactive_loop(customer_agent_client, supports_streaming)

    except httpx.HTTPStatusError as e:
        print(f"Request failed with HTTP status: {e.response.status_code}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option( "--agent", default="http://localhost:10002", help="Base URL of the A2A agent server")

def main(agent: str) -> None:
    asyncio.run(run_main(agent))

if __name__ == "__main__":
    main()