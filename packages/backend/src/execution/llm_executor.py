"""LLM workflow executor — renders prompt, calls LLM API, returns text."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.crypto import decrypt_api_key
from src.db.models import ExecutionLog, LLMModel, Workflow
from src.execution.log_helper import finish_log
from src.execution.template import render_prompt
from src.integrations.llm_providers import get_api_format

logger = logging.getLogger(__name__)


class LLMExecutionError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _build_request(llm_model: LLMModel, prompt: str, temperature: float) -> tuple[str, dict, dict, str]:
    """Build URL, payload, headers, and response_path for an LLM request."""
    base_url = llm_model.base_url.rstrip("/")
    endpoint = llm_model.endpoint_execute.rstrip("/")
    url = f"{base_url}{endpoint}"
    api_format = get_api_format(llm_model.provider_type)
    api_key = decrypt_api_key(llm_model.api_key)

    headers: dict[str, str] = {"Content-Type": "application/json"}

    if api_format == "ollama":
        options: dict[str, Any] = {"temperature": temperature}
        if llm_model.context_length is not None:
            options["num_ctx"] = llm_model.context_length
        payload = {
            "model": llm_model.model_id,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        response_path = "response"

    elif api_format == "anthropic":
        payload = {
            "model": llm_model.model_id,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        response_path = "content[0].text"
        if api_key:
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"

    else:
        # OpenAI-compatible (openai, openrouter, deepseek, mistral, google, groq, custom_openai)
        payload = {
            "model": llm_model.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "stream": False,
        }
        response_path = "choices[0].message.content"
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    return url, payload, headers, response_path


async def execute_llm_workflow(
    workflow: Workflow,
    input_data: dict[str, Any],
    db: AsyncSession,
    user_id: UUID,
    client_version: Optional[str] = None,
    client_platform: Optional[str] = None,
) -> dict[str, Any]:
    """Execute a text_transformation workflow using the assigned LLM model."""
    if not workflow.llm_model_id:
        raise LLMExecutionError("Workflow has no LLM model assigned")

    llm_model: LLMModel | None = await db.get(LLMModel, workflow.llm_model_id)
    if llm_model is None or not llm_model.is_active:
        raise LLMExecutionError("Assigned LLM model not found or inactive")

    if not workflow.prompt_template:
        raise LLMExecutionError("Workflow has no prompt template configured")

    # Render the prompt
    prompt = render_prompt(workflow.prompt_template, input_data)
    temperature = workflow.temperature if workflow.temperature is not None else llm_model.default_temperature

    # Create execution log
    execution_log = ExecutionLog(
        workflow_id=workflow.id,
        user_id=user_id,
        status="running",
        input_preview=prompt[:200],
        client_version=client_version,
        client_platform=client_platform,
    )
    db.add(execution_log)
    await db.flush()

    start_time = datetime.now(timezone.utc)
    timeout = float(workflow.timeout_seconds or llm_model.default_timeout_seconds)

    try:
        url, payload, headers, response_path = _build_request(llm_model, prompt, temperature)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        response_data = response.json()

        # Extract result text
        from src.execution.template import extract_response
        result_text = extract_response(response_data, f"$.{response_path}")

        duration_ms = finish_log(execution_log, start_time, status="success",
                                 output_preview=result_text)
        await db.flush()

        action = workflow.output_action or "replace_selection"

        return {
            "text": result_text,
            "action": action,
            "success": True,
            "execution_log_id": str(execution_log.id),
            "duration_ms": duration_ms,
            "metadata": {"duration_ms": duration_ms},
        }

    except httpx.HTTPStatusError as e:
        error_msg = f"LLM service returned HTTP {e.response.status_code}"
        logger.error("LLM HTTP %d from %s: %s", e.response.status_code, url, e.response.text[:500])
        finish_log(execution_log, start_time, status="error", error_message=error_msg)
        await db.flush()
        raise LLMExecutionError(error_msg) from e

    except httpx.HTTPError as e:
        error_msg = "Cannot reach LLM service"
        logger.error("LLM request to %s failed: %r", url, e)
        finish_log(execution_log, start_time, status="error", error_message=error_msg)
        await db.flush()
        raise LLMExecutionError(error_msg) from e

    except LLMExecutionError:
        raise

    except Exception as e:
        logger.error("Unexpected LLM execution error: %s", e)
        finish_log(execution_log, start_time, status="error",
                   error_message=str(e)[:1000])
        await db.flush()
        raise LLMExecutionError("Unexpected execution error") from e
