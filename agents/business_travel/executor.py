# agents/business_travel/executor.py

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus

from agents.business_travel.agent import BusinessTravelAgent

logger = logging.getLogger(__name__)


class BusinessTravelExecutor(AgentExecutor):
    """Adapter between the A2A server framework and BusinessTravelAgent."""

    def __init__(self, agent: BusinessTravelAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Enqueue initial Task object - required before any TaskStatusUpdateEvent.
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
            logger.info(f"BusinessTravelAgent received: {user_text} (context: {context_id})")

            response, input_required = await self.agent.invoke(user_text, context_id)
            logger.info(f"BusinessTravelAgent result: {response[:200]}")

            reply = updater.new_agent_message(parts=[Part(text=response)])

            if input_required:
                await updater.update_status(
                    state=TaskState.TASK_STATE_INPUT_REQUIRED,
                    message=reply,
                )
            else:
                await updater.complete(message=reply)

        except Exception as e:
            logger.error(f"BusinessTravelAgent error: {e}")
            error_msg = updater.new_agent_message(parts=[Part(text=f"Error: {e}")])
            await updater.failed(message=error_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()
