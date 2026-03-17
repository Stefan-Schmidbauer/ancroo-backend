"""Workflow execution dispatcher — routes to the appropriate executor."""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Workflow
from src.execution.llm_executor import LLMExecutionError, execute_llm_workflow
from src.execution.stt_executor import STTExecutionError, execute_stt_workflow
from src.execution.tool_executor import ToolExecutionError, execute_tool_workflow


class ExecutionError(Exception):
    """Base execution error raised by the dispatcher."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def execute_workflow(
    workflow: Workflow,
    input_data: dict[str, Any],
    db: AsyncSession,
    user_id: UUID,
    client_version: Optional[str] = None,
    client_platform: Optional[str] = None,
    file_name: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> dict[str, Any]:
    """Dispatch workflow execution to the appropriate executor.

    Routes based on which FK is set: llm_model_id, stt_model_id, or tool_id.
    """
    try:
        if workflow.llm_model_id:
            return await execute_llm_workflow(
                workflow, input_data, db, user_id,
                client_version=client_version,
                client_platform=client_platform,
            )
        elif workflow.stt_model_id:
            return await execute_stt_workflow(
                workflow, input_data, db, user_id,
                client_version=client_version,
                client_platform=client_platform,
                file_name=file_name,
                file_size_bytes=file_size_bytes,
            )
        elif workflow.tool_id:
            return await execute_tool_workflow(
                workflow, input_data, db, user_id,
                client_version=client_version,
                client_platform=client_platform,
                file_name=file_name,
                file_size_bytes=file_size_bytes,
            )
        else:
            raise ExecutionError("Workflow has no execution target configured")

    except (LLMExecutionError, STTExecutionError, ToolExecutionError) as e:
        raise ExecutionError(e.message)
