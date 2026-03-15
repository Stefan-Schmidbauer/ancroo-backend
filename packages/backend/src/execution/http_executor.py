"""Generic HTTP-based workflow executor.

Every workflow (text transformation, workflow trigger, custom) is ultimately
an HTTP request. This executor:
1. Takes input data from the extension (text, clipboard, fields, context)
2. Renders the payload via Jinja2 template
3. Makes an HTTP request to the configured target
4. Extracts the result text via response_mapping
5. Returns the result with the configured output action
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ExecutionLog, Workflow


class HttpExecutionError(Exception):
    """Error during HTTP workflow execution."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _json_escape(value: str) -> str:
    """Escape a string so it is safe inside a JSON string literal.

    ``json.dumps`` adds surrounding quotes; we strip them so the value
    can be interpolated into an already-quoted JSON template.
    """
    return json.dumps(value)[1:-1]


def _render_payload(template_str: str, input_data: dict[str, Any]) -> str:
    """Render a Jinja2 payload template with input data.

    Available variables: text, html, clipboard, fields, context, url, title,
    and a special _input variable containing the full input dict.

    String values are JSON-escaped so that newlines, quotes, and other
    special characters do not break the resulting JSON payload.
    """
    env = SandboxedEnvironment()
    template = env.from_string(template_str)

    text = input_data.get("text", "")
    html = input_data.get("html", "")
    clipboard = input_data.get("clipboard", "")
    context = input_data.get("context", {})

    # Build template variables — escape strings for safe JSON embedding
    variables = {
        "text": _json_escape(text),
        "html": _json_escape(html),
        "clipboard": _json_escape(clipboard),
        "fields": input_data.get("fields", {}),
        "context": context,
        "url": _json_escape(context.get("url", "")),
        "title": _json_escape(context.get("title", "")),
        "_input": input_data,
    }

    return template.render(**variables)


def _extract_response(data: Any, mapping: str) -> str:
    """Extract a value from response data using a simple dot/bracket path.

    Supports paths like:
    - $.response
    - $.choices[0].message.content
    - $.result.text

    Args:
        data: Parsed JSON response
        mapping: JSONPath-like expression (simplified)

    Returns:
        Extracted string value.
    """
    if not mapping:
        # No mapping — return raw response as string
        return str(data) if not isinstance(data, str) else data

    # Strip leading $. if present
    path = mapping.lstrip("$").lstrip(".")

    current = data
    # Split on dots, handling array indices like [0]
    parts = re.split(r"\.(?![^\[]*\])", path)

    for part in parts:
        if not part:
            continue

        # Check for array index: field[0]
        match = re.match(r"^(\w+)\[(\d+)\]$", part)
        if match:
            field, index = match.group(1), int(match.group(2))
            if isinstance(current, dict) and field in current:
                current = current[field]
                if isinstance(current, list) and index < len(current):
                    current = current[index]
                else:
                    return ""
            else:
                return ""
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return ""

    return str(current) if not isinstance(current, str) else current


async def execute_http_workflow(
    workflow: Workflow,
    input_data: dict[str, Any],
    db: AsyncSession,
    user_id: UUID,
    client_version: Optional[str] = None,
    client_platform: Optional[str] = None,
    file_name: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> dict[str, Any]:
    """Execute a workflow via generic HTTP request.

    Supports both JSON payloads and multipart file uploads. When target_config
    contains ``file_field_name`` and input_data contains ``file_path``, the
    request is sent as multipart/form-data with the file attached.

    Args:
        workflow: Workflow with target_config and output_action set
        input_data: Data collected by extension (text, clipboard, fields, context)
        db: Database session for execution logging
        user_id: User executing the workflow
        client_version: Client version string
        client_platform: Client platform string
        file_name: Original filename of uploaded file (for logging)
        file_size_bytes: Size of uploaded file in bytes (for logging)

    Returns:
        Result dict with text, action, success keys.
    """
    target = workflow.target_config

    # Resolve LLM provider target at runtime when a provider is assigned.
    # This overrides the baked-in URL/model with live values from the DB.
    if workflow.llm_provider_id and target:
        from src.db.models import LLMProvider as LLMProviderModel
        from src.integrations.llm_provider import build_runtime_target, LLMProviderError
        provider_model = await db.get(LLMProviderModel, workflow.llm_provider_id)
        if provider_model is None or not provider_model.is_active:
            raise HttpExecutionError(
                f"Assigned LLM provider {workflow.llm_provider_id} not found or inactive"
            )
        try:
            target = build_runtime_target(provider_model, workflow.llm_model, target)
        except LLMProviderError as e:
            raise HttpExecutionError(f"LLM provider error: {e.message}")

    # Resolve STT provider target at runtime when a provider is assigned.
    if workflow.stt_provider_id and target:
        from src.db.models import STTProvider as STTProviderModel
        from src.integrations.stt_provider import build_runtime_stt_target, STTProviderError
        stt_provider = await db.get(STTProviderModel, workflow.stt_provider_id)
        if stt_provider is None or not stt_provider.is_active:
            raise HttpExecutionError(
                f"Assigned STT provider {workflow.stt_provider_id} not found or inactive"
            )
        try:
            target = build_runtime_stt_target(stt_provider, workflow.stt_model, target)
        except STTProviderError as e:
            raise HttpExecutionError(f"STT provider error: {e.message}")

    if not target or not target.get("url"):
        preset = target.get("_preset", "") if target else ""
        if preset == "n8n":
            raise HttpExecutionError(
                "n8n webhook not configured. "
                "Run './module.sh setup ancroo-backend' or configure the webhook URL in the admin panel."
            )
        raise HttpExecutionError("Workflow has no target URL configured")

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

    try:
        # Build HTTP request from target_config
        url = target["url"]
        method = target.get("method", "POST").upper()
        timeout = target.get("timeout", 120)
        response_mapping = target.get("response_mapping", "")

        # Detect file upload mode
        file_field_name = target.get("file_field_name")
        file_path = input_data.get("file_path")
        is_file_upload = file_field_name and file_path

        # Make HTTP request
        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            if is_file_upload:
                # Multipart file upload mode
                file_info = input_data.get("file_info", {})
                form_fields_config = target.get("form_fields", {})

                # Render form field values via Jinja2
                form_data = {}
                for key, template_val in form_fields_config.items():
                    form_data[key] = _render_payload(str(template_val), input_data)

                with open(file_path, "rb") as fh:
                    files = {
                        file_field_name: (
                            file_info.get("filename", "upload"),
                            fh,
                            file_info.get("content_type", "application/octet-stream"),
                        )
                    }
                    if method == "POST":
                        response = await client.post(
                            url, data=form_data, files=files,
                        )
                    elif method == "PUT":
                        response = await client.put(
                            url, data=form_data, files=files,
                        )
                    else:
                        raise HttpExecutionError(
                            f"Unsupported HTTP method for file upload: {method}"
                        )

                response.raise_for_status()
            else:
                # Standard JSON mode
                headers = target.get("headers", {"Content-Type": "application/json"})
                payload_template = target.get("payload_template", "")

                # Render payload
                payload_str = _render_payload(payload_template, input_data)

                # Parse payload as JSON (most targets expect JSON)
                try:
                    payload = json.loads(payload_str)
                except json.JSONDecodeError:
                    payload = None

                if method == "POST":
                    if payload is not None:
                        response = await client.post(url, json=payload, headers=headers)
                    else:
                        response = await client.post(
                            url, content=payload_str, headers=headers
                        )
                elif method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "PUT":
                    response = await client.put(url, json=payload, headers=headers)
                else:
                    raise HttpExecutionError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

        # Parse response
        try:
            response_data = response.json()
        except (json.JSONDecodeError, ValueError):
            response_data = response.text

        # Extract result text via mapping
        result_text = _extract_response(response_data, response_mapping)

        # Determine output action
        action = workflow.output_action or "replace_selection"

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        execution_log.status = "success"
        execution_log.output_preview = result_text[:200] if result_text else None
        execution_log.completed_at = end_time
        execution_log.duration_ms = duration_ms
        await db.flush()

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
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        logger.error("Upstream HTTP %d from %s: %s", e.response.status_code, url, e.response.text[:500])
        error_msg = f"Upstream service returned HTTP {e.response.status_code}"

        execution_log.status = "error"
        execution_log.error_message = error_msg
        execution_log.completed_at = end_time
        execution_log.duration_ms = duration_ms
        await db.flush()

        raise HttpExecutionError(error_msg)

    except httpx.HTTPError as e:
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        logger.error("HTTP request to %s failed: %s", url, e)
        error_msg = "Cannot reach upstream service"

        execution_log.status = "error"
        execution_log.error_message = error_msg
        execution_log.completed_at = end_time
        execution_log.duration_ms = duration_ms
        await db.flush()

        raise HttpExecutionError(error_msg)

    except HttpExecutionError:
        raise

    except Exception as e:
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        execution_log.status = "error"
        execution_log.error_message = str(e)[:1000]
        execution_log.completed_at = end_time
        execution_log.duration_ms = duration_ms
        await db.flush()

        logger.error("Unexpected error executing workflow against %s: %s", url, e)
        raise HttpExecutionError("Unexpected execution error")
