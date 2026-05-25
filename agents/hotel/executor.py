# agents/hotel/executor.py

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus

from agents.hotel.agent import HotelAgent

logger = logging.getLogger(__name__)


class HotelExecutor(AgentExecutor):
    """Adapter between the A2A server framework and HotelAgent.
    
    Supports INPUT_REQUIRED state for multi-turn booking conversations.
    """

    def __init__(self, agent: HotelAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Enqueue initial Task object — required before any TaskStatusUpdateEvent
        task = context.current_task
        if not task:       
            await event_queue.enqueue_event(Task(  
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )) # Enqueue the initial Task object — required by the A2A protocol before any TaskStatusUpdateEvent can be sent
            

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        try:
            await updater.start_work()
            user_text = context.get_user_input()
            # Pass context_id so HotelAgent can maintain per-conversation state
            context_id = context.context_id or context.task_id
            logger.info(f"HotelAgent received: {user_text} (context: {context_id})")

            response, input_required = await self.agent.invoke(user_text, context_id)
            logger.info(f"HotelAgent result: {response[:200]}")

            reply = updater.new_agent_message(parts=[Part(text=response)])

            if input_required:
                # Agent needs more input — tell the client to send another message
                await updater.update_status(
                    state=TaskState.TASK_STATE_INPUT_REQUIRED,
                    message=reply,
                )
            else:
                await updater.complete(message=reply)

        except Exception as e:
            logger.error(f"HotelAgent error: {e}")
            error_msg = updater.new_agent_message(parts=[Part(text=f"Error: {e}")])
            await updater.failed(message=error_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()