import logging
import uuid

from a2a.types import  Message, Part, Role, SendMessageRequest, TaskState


logger = logging.getLogger(__name__)


class CustomerAgent:
    """Customer-facing agent that acts as the entry point for user messages.
    
    Receives user messages from the A2A server, wraps them in a SendMessageRequest
    and forwards them to the Orchestrator via the A2A SDK client. The response from
    the Orchestrator is extracted and returned as plain text.
    
    Has no LLM logic of its own — all intelligence lives in the Orchestrator.
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self, client):
        self._client = client


    async def invoke(self, query: str, context_id: str | None = None) -> tuple[str, bool]:
        """Forwards the user query to the orchestrator and returns its response."""
        request = SendMessageRequest(message=Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=query)], context_id=context_id or "")) # Wrap the user text in an A2A Message object with a unique ID

        input_required = False
        response_parts = []
        # Send request to the orchestrator via the A2A SDK client. Even in non-streaming mode,
        # send_message returns an async iterator yielding a single StreamResponse (protobuf oneof).
        async for result in self._client.send_message(request): 
            field = result.WhichOneof("payload")  # WhichOneof("payload") returns the name of whichever field is currently set.
            if field == "message":  # Direct message response — text is in message.parts
                for part in result.message.parts:
                    if getattr(part, "text", None):
                        response_parts.append(part.text)
            elif field == "task":   # Task response — text is nested in task.status.message.parts
                if result.task.status.HasField("message"):
                    for part in result.task.status.message.parts:
                        if getattr(part, "text", None):
                            response_parts.append(part.text)
                # Check if orchestrator is waiting for input
                if result.task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                    input_required = True
        return "\n".join(response_parts) if response_parts else "(no response from orchestrator)", input_required
