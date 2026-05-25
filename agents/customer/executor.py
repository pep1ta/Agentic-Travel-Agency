import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Part, TaskState, Task,TaskStatus
from agents.customer.agent import CustomerAgent

logger = logging.getLogger(__name__)


class CustomerExecutor(AgentExecutor):
    """Adapter between the A2A server framework and CustomerAgent.
    Reads user input from the RequestContext, calls the CustomerAgent,
    and publishes task state updates to the EventQueue.
    """

    def __init__(self, agent: CustomerAgent):
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
            await updater.start_work() # Publishes TASK_STATE_WORKING to the EventQueue
            user_text = context.get_user_input() # Extract the user's text from the incoming request
            logger.info(f"CustomerAgent received: {user_text}")

            result, input_required = await self.agent.invoke(user_text, context_id=context.context_id) # Forward to orchestrator and wait for response
            logger.info(f"CustomerAgent result: {result[:200]}")
            reply = updater.new_agent_message(parts=[Part(text=result)]) # Wrap response text in a Message object
            if input_required:
                await updater.update_status(state=TaskState.TASK_STATE_INPUT_REQUIRED, message=reply) # Publishes TASK_STATE_INPUT_REQUIRED to the EventQueue
            else:
                await updater.complete(message=reply) # Publishes TASK_STATE_COMPLETED with the reply to the EventQueue

        except Exception as e:
            logger.error(f"CustomerAgent error: {e}")
            error_msg = updater.new_agent_message(parts=[Part(text=f"Error: {e}")])
            await updater.failed(message=error_msg)

 
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel() # Publishes TASK_STATE_CANCELED to the EventQueue