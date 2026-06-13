# agents/flight/executor.py

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus

from agents.flight.agent import FlightProviderAgent

logger = logging.getLogger(__name__)


class FlightProviderExecutor(AgentExecutor):
    """Adapter between the A2A server framework and FlightProviderAgent."""

    def __init__(self, agent: FlightProviderAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if not task:
            await event_queue.enqueue_event(Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            ))

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        try:
            await updater.start_work()
            user_text = context.get_user_input()
            context_id = context.context_id or context.task_id

            response, _ = await self.agent.invoke(user_text, context_id)
            reply = updater.new_agent_message(parts=[Part(text=response)])
            await updater.complete(message=reply)

        except Exception as e:
            logger.error(f"FlightProviderAgent error: {e}")
            error_msg = updater.new_agent_message(parts=[Part(text=f"Error: {e}")])
            await updater.failed(message=error_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()
