"""Pipeline-based workflow execution engine.

Executes workflows defined as ordered pipeline steps (stored as JSONB).
Each step transforms the current text and passes it to the next step.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ExecutionLog, Workflow
from src.integrations.ollama import generate as ollama_generate, OllamaError


class PipelineExecutionError(Exception):
    """Error during pipeline execution."""

    def __init__(self, message: str, step_index: int = -1):
        self.message = message
        self.step_index = step_index
        super().__init__(message)


def _render_prompt(template_str: str, variables: dict[str, Any]) -> str:
    """Render a Jinja2 prompt template with the given variables.

    Available variables: text, url, title, and anything in context.
    """
    env = SandboxedEnvironment()
    template = env.from_string(template_str)
    return template.render(**variables)


async def execute_pipeline(
    workflow: Workflow,
    input_data: dict[str, Any],
    db: AsyncSession,
    user_id: UUID,
    client_version: Optional[str] = None,
    client_platform: Optional[str] = None,
) -> dict[str, Any]:
    """Execute a pipeline workflow.

    Iterates through pipeline_steps in order. Each step receives the current
    text and produces new text for the next step.

    Args:
        workflow: Workflow with pipeline_steps defined
        input_data: Dict with 'text' and optional 'context'
        db: Database session
        user_id: User executing the workflow
        client_version: Client version (for logging)
        client_platform: Client platform (for logging)

    Returns:
        Result dict with text, action, success keys.
    """
    steps = workflow.pipeline_steps or []
    if not steps:
        raise PipelineExecutionError("Workflow has no pipeline steps defined")

    # Create execution log
    execution_log = ExecutionLog(
        workflow_id=workflow.id,
        user_id=user_id,
        status="running",
        input_preview=json.dumps(input_data)[:200] if input_data else None,
        client_version=client_version,
        client_platform=client_platform,
    )
    db.add(execution_log)
    await db.flush()

    start_time = datetime.now(timezone.utc)
    current_text = input_data.get("text", "")
    context = input_data.get("context", {})

    try:
        for i, step in enumerate(steps):
            step_type = step.get("type", "llm")

            if step_type == "llm":
                current_text = await _execute_llm_step(step, current_text, context, input_data)
            elif step_type == "transform":
                current_text = _execute_transform_step(step, current_text)
            else:
                raise PipelineExecutionError(
                    f"Unknown step type: {step_type}", step_index=i
                )

        # Determine output action — prefer output_action, fall back to output_type
        action = workflow.output_action or workflow.output_type or "replace_selection"

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        execution_log.status = "success"
        execution_log.output_preview = current_text[:200]
        execution_log.completed_at = end_time
        execution_log.duration_ms = duration_ms
        await db.flush()

        return {
            "text": current_text,
            "action": action,
            "success": True,
            "execution_log_id": str(execution_log.id),
            "duration_ms": duration_ms,
            "metadata": {"steps_executed": len(steps), "duration_ms": duration_ms},
        }

    except (PipelineExecutionError, OllamaError) as e:
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        execution_log.status = "error"
        execution_log.error_message = str(e)[:1000]
        execution_log.completed_at = end_time
        execution_log.duration_ms = duration_ms
        await db.flush()

        raise PipelineExecutionError(str(e))

    except Exception as e:
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        execution_log.status = "error"
        execution_log.error_message = str(e)[:1000]
        execution_log.completed_at = end_time
        execution_log.duration_ms = duration_ms
        await db.flush()

        raise PipelineExecutionError(f"Unexpected error: {e}")


async def _execute_llm_step(
    step: dict[str, Any],
    text: str,
    context: dict[str, Any],
    input_data: dict[str, Any] | None = None,
) -> str:
    """Execute an LLM pipeline step.

    Args:
        step: Step config with 'model', 'prompt_template', 'temperature'
        text: Current text
        context: Additional context (url, title, etc.)
        input_data: Full input data dict (for accessing html, etc.)

    Returns:
        LLM-generated text.
    """
    model = step.get("model", "mistral:7b")
    prompt_template = step.get("prompt_template", "{{text}}")
    temperature = step.get("temperature", 0.3)

    # Build template variables
    variables = {"text": text, **context}
    if input_data:
        variables["html"] = input_data.get("html", "")

    prompt = _render_prompt(prompt_template, variables)
    return await ollama_generate(
        model=model,
        prompt=prompt,
        temperature=temperature,
    )


def _execute_transform_step(step: dict[str, Any], text: str) -> str:
    """Execute a text transform step.

    Args:
        step: Step config with 'operation'
        text: Current text

    Returns:
        Transformed text.
    """
    operation = step.get("operation", "trim")
    if operation == "uppercase":
        return text.upper()
    elif operation == "lowercase":
        return text.lower()
    elif operation == "trim":
        return text.strip()
    else:
        return text
