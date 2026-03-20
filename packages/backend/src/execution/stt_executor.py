"""STT workflow executor — sends audio file to Whisper API, returns transcription."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ExecutionLog, STTModel, Workflow
from src.execution.log_helper import finish_log

logger = logging.getLogger(__name__)


class STTExecutionError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def execute_stt_workflow(
    workflow: Workflow,
    input_data: dict[str, Any],
    db: AsyncSession,
    user_id: UUID,
    client_version: Optional[str] = None,
    client_platform: Optional[str] = None,
    file_name: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
) -> dict[str, Any]:
    """Execute a speech_to_text workflow using the assigned STT model."""
    if not workflow.stt_model_id:
        raise STTExecutionError("Workflow has no STT model assigned")

    stt_model: STTModel | None = await db.get(STTModel, workflow.stt_model_id)
    if stt_model is None or not stt_model.is_active:
        raise STTExecutionError("Assigned STT model not found or inactive")

    file_path = input_data.get("file_path")
    if not file_path:
        raise STTExecutionError("No audio file provided")

    # Validate file_path is inside the upload temp directory
    from src.config import get_settings
    _settings = get_settings()
    _upload_dir = Path(_settings.upload_temp_dir).resolve()
    if not Path(file_path).resolve().is_relative_to(_upload_dir):
        raise STTExecutionError("Invalid file path")

    file_info = input_data.get("file_info", {})

    # Create execution log
    execution_log = ExecutionLog(
        workflow_id=workflow.id,
        user_id=user_id,
        status="running",
        input_preview=f"Audio: {file_info.get('filename', 'upload')}",
        client_version=client_version,
        client_platform=client_platform,
        file_name=file_name,
        file_size_bytes=file_size_bytes,
    )
    db.add(execution_log)
    await db.flush()

    start_time = datetime.now(timezone.utc)
    url = f"{stt_model.base_url.rstrip('/')}/v1/audio/transcriptions"
    timeout = float(workflow.timeout_seconds)

    try:
        # Build multipart form data
        form_data = {"model": stt_model.model_id}
        if stt_model.default_language:
            form_data["language"] = stt_model.default_language

        headers = {}
        if stt_model.api_key:
            headers["Authorization"] = f"Bearer {stt_model.api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(file_path, "rb") as fh:
                files = {
                    "file": (
                        file_info.get("filename", "upload.wav"),
                        fh,
                        file_info.get("content_type", "audio/wav"),
                    )
                }
                response = await client.post(
                    url, data=form_data, files=files, headers=headers,
                )
                response.raise_for_status()

        response_data = response.json()
        result_text = response_data.get("text", "")

        duration_ms = finish_log(execution_log, start_time, status="success",
                                 output_preview=result_text)
        await db.flush()

        action = workflow.output_action or "copy_to_clipboard"

        return {
            "text": result_text,
            "action": action,
            "success": True,
            "execution_log_id": str(execution_log.id),
            "duration_ms": duration_ms,
            "metadata": {"duration_ms": duration_ms},
        }

    except httpx.HTTPStatusError as e:
        error_msg = f"STT service returned HTTP {e.response.status_code}"
        logger.error("STT HTTP %d from %s: %s", e.response.status_code, url, e.response.text[:500])
        finish_log(execution_log, start_time, status="error", error_message=error_msg)
        await db.flush()
        raise STTExecutionError(error_msg) from e

    except httpx.HTTPError as e:
        error_msg = "Cannot reach STT service"
        logger.error("STT request to %s failed: %s", url, e)
        finish_log(execution_log, start_time, status="error", error_message=error_msg)
        await db.flush()
        raise STTExecutionError(error_msg) from e

    except STTExecutionError:
        raise

    except Exception as e:
        logger.error("Unexpected STT execution error: %s", e)
        finish_log(execution_log, start_time, status="error",
                   error_message=str(e)[:1000])
        await db.flush()
        raise STTExecutionError("Unexpected execution error") from e
