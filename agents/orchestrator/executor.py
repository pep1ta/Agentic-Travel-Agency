import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus

from agents.orchestrator.agent import OrchestratorAgent

logger = logging.getLogger(__name__)


class OrchestratorExecutor(AgentExecutor):
    """Thin adapter between the A2A server framework and OrchestratorAgent."""

    def __init__(self, agent: OrchestratorAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Called by the A2A server (via DefaultRequestHandler -> ActiveTask) on each incoming request."""
        task = context.current_task
        if not task:       
            await event_queue.enqueue_event(Task(  
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )) # Enqueue the initial Task object — required by the A2A protocol before any TaskStatusUpdateEvent can be sent
            
        updater = TaskUpdater(event_queue, context.task_id, context.context_id) # TaskUpdater is a helper that simplifies publishing task state updates to the EventQueue

        try:
            await updater.submit() # Publishes TASK_STATE_SUBMITTED to the EventQueue
            await updater.start_work() # Publishes TASK_STATE_WORKING to the EventQueue
            user_text = context.get_user_input() # Extract the user's text from the incoming request
            logger.info(f"Orchestrator received: {user_text}")

            result, input_required = await self.agent.invoke(user_text, context_id=context.context_id) # Core orchestrator logic is called here — this may involve multiple calls to sub-agents and tools before a final answer is produced
            reply = updater.new_agent_message(parts=[Part(text=result)]) # Wrap response text in a Message object
            if input_required:
                await updater.update_status(state=TaskState.TASK_STATE_INPUT_REQUIRED, message=reply) # Publishes TASK_STATE_INPUT_REQUIRED to the EventQueue
            else:
                await updater.complete(message=reply) # Publishes TASK_STATE_COMPLETED to the EventQueue

        except Exception as e:
            logger.error(f"Orchestrator error: {e}")
            error_msg = updater.new_agent_message(parts=[Part(text=f"Error: {e}")])
            await updater.failed(message=error_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel() # Publishes TASK_STATE_CANCELED to the EventQueue