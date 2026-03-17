"""Tool workflow executor — calls AR plugins, n8n webhooks, or custom APIs."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ExecutionLog, Tool, Workflow
from src.execution.log_helper import finish_log
from src.execution.template import extract_response, render_payload

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def execute_tool_workflow(
    workflow: Workflow,
    input_data: dict[str, Any],
    db: AsyncSession,
    user_id: UUID,
    client_version: Optional[str] = None,
    client_platform: Optional[str] = None,
    file_name: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> dict[str, Any]:
    """Execute a tool workflow (AR plugin, n8n webhook, or custom API)."""
    if not workflow.tool_id:
        raise ToolExecutionError("Workflow has no tool assigned")

    tool: Tool | None = await db.get(Tool, workflow.tool_id)
    if tool is None or not tool.is_active:
        raise ToolExecutionError("Assigned tool not found or inactive")

    # Create execution log
    execution_log = ExecutionLog(
        workflow_id=workflow.id,
        user_id=user_id,
        status="running",
        input_preview=json.dumps(input_data, default=str)[:200],
        client_version=client_version,
        client_platform=client_platform,
        file_name=file_name,
        file_size_bytes=file_size_bytes,
    )
    db.add(execution_log)
    await db.flush()

    start_time = datetime.now(timezone.utc)
    url = tool.endpoint_url
    method = (tool.http_method or "POST").upper()
    timeout = float(tool.timeout or 120)

    try:
        headers = dict(tool.headers) if tool.headers else {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            if tool.payload_template:
                payload_str = render_payload(tool.payload_template, input_data)
                try:
                    payload = json.loads(payload_str)
                except json.JSONDecodeError:
                    payload = None

                if method == "POST":
                    if payload is not None:
                        response = await client.post(url, json=payload, headers=headers)
                    else:
                        response = await client.post(url, content=payload_str, headers=headers)
                elif method == "PUT":
                    response = await client.put(url, json=payload, headers=headers)
                elif method == "GET":
                    response = await client.get(url, headers=headers)
                else:
                    raise ToolExecutionError(f"Unsupported HTTP method: {method}")
            else:
                # No template — send input_data as JSON directly
                if method == "POST":
                    response = await client.post(url, json=input_data, headers=headers)
                elif method == "PUT":
                    response = await client.put(url, json=input_data, headers=headers)
                elif method == "GET":
                    response = await client.get(url, headers=headers)
                else:
                    raise ToolExecutionError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()

        # Parse response
        try:
            response_data = response.json()
        except (json.JSONDecodeError, ValueError):
            response_data = response.text

        # Extract result text
        result_text = extract_response(response_data, tool.response_mapping or "")

        duration_ms = finish_log(execution_log, start_time, status="success",
                                 output_preview=result_text)
        await db.flush()

        action = workflow.output_action or "replace_selection"
        metadata: dict[str, Any] = {"duration_ms": duration_ms}

        # For download_file actions, pass filename and mime_type from upstream
        if action == "download_file" and isinstance(response_data, dict):
            if response_data.get("filename"):
                metadata["filename"] = response_data["filename"]
            if response_data.get("mime_type"):
                metadata["mime_type"] = response_data["mime_type"]

        return {
            "text": result_text,
            "action": action,
            "success": True,
            "execution_log_id": str(execution_log.id),
            "duration_ms": duration_ms,
            "metadata": metadata,
        }

    except httpx.HTTPStatusError as e:
        error_msg = f"Tool service returned HTTP {e.response.status_code}"
        logger.error("Tool HTTP %d from %s: %s", e.response.status_code, url, e.response.text[:500])
        finish_log(execution_log, start_time, status="error", error_message=error_msg)
        await db.flush()
        raise ToolExecutionError(error_msg) from e

    except httpx.HTTPError as e:
        error_msg = "Cannot reach tool service"
        logger.error("Tool request to %s failed: %s", url, e)
        finish_log(execution_log, start_time, status="error", error_message=error_msg)
        await db.flush()
        raise ToolExecutionError(error_msg) from e

    except ToolExecutionError:
        raise

    except Exception as e:
        logger.error("Unexpected tool execution error: %s", e)
        finish_log(execution_log, start_time, status="error",
                   error_message=str(e)[:1000])
        await db.flush()
        raise ToolExecutionError("Unexpected execution error") from e
