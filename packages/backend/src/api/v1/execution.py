"""Workflow execution API endpoints."""

import json
import logging
import os
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from src.config import get_settings
from src.db.models import Workflow
from src.auth.permissions import can_user_access_workflow
from src.workflows.pipeline_executor import execute_pipeline, PipelineExecutionError
from src.execution.http_executor import execute_http_workflow, HttpExecutionError
from src.utils.audio import NATIVE_AUDIO_TYPES, AudioConversionError, convert_audio_to_wav
from src.api.v1.schemas import (
    ExecuteWorkflowRequest,
    ExecuteWorkflowResponse,
    ExecutionResult,
)
from src.api.v1.dependencies import CurrentUser, DbSession

router = APIRouter(prefix="/workflows", tags=["execution"])

logger = logging.getLogger(__name__)


@router.post("/{slug}/execute", response_model=ExecuteWorkflowResponse)
async def execute_workflow(
    slug: str,
    request: ExecuteWorkflowRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Execute a workflow.

    The client sends input data (usually selected text from the browser).
    The server routes to the configured execution backend and returns the result.
    """
    # Find workflow by slug
    result = await db.execute(select(Workflow).where(Workflow.slug == slug))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{slug}' not found",
        )

    # Check permission
    if not await can_user_access_workflow(db, user, workflow.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this workflow",
        )

    if not workflow.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This workflow is currently inactive",
        )

    # Prepare input data — support both legacy and new format
    input_data = {
        "text": request.input_data.text,
        "html": request.input_data.html,
        "context": request.input_data.context,
    }
    if request.input_data.clipboard:
        input_data["clipboard"] = request.input_data.clipboard
    if request.input_data.fields:
        input_data["fields"] = request.input_data.fields
    if request.client_script_result:
        input_data["client_result"] = request.client_script_result

    try:
        if workflow.workflow_type:
            output = await execute_http_workflow(
                workflow=workflow,
                input_data=input_data,
                db=db,
                user_id=user.id,
                client_version=request.client_version,
                client_platform=request.client_platform,
            )
        elif workflow.execution_type == "pipeline":
            output = await execute_pipeline(
                workflow=workflow,
                input_data=input_data,
                db=db,
                user_id=user.id,
                client_version=request.client_version,
                client_platform=request.client_platform,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow has no execution target configured",
            )

        result_data = ExecutionResult(
            text=output.get("text"),
            action=output.get("action", "replace_selection"),
            success=output.get("success", True),
            error=output.get("error"),
            metadata=output.get("metadata", {}),
        )

        execution_log_id = output.get("execution_log_id")

        return ExecuteWorkflowResponse(
            execution_id=UUID(execution_log_id) if execution_log_id else workflow.id,
            status="success",
            result=result_data,
            duration_ms=output.get("duration_ms"),
        )

    except (HttpExecutionError, PipelineExecutionError) as e:
        return ExecuteWorkflowResponse(
            execution_id=uuid4(),
            status="error",
            result=ExecutionResult(
                text=None,
                action="none",
                success=False,
                error=e.message,
            ),
            duration_ms=None,
        )


@router.post("/{slug}/execute-upload", response_model=ExecuteWorkflowResponse)
async def execute_workflow_with_file(
    slug: str,
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    input_data: str = Form(default="{}"),
    client_version: Optional[str] = Form(default=None),
    client_platform: Optional[str] = Form(default=None),
):
    """Execute a workflow with a file upload.

    The file is saved to a temp directory and forwarded to the target backend
    (e.g. service-tools /transcribe). Temp files are cleaned up after processing.
    """
    settings = get_settings()

    # Find workflow by slug
    result = await db.execute(select(Workflow).where(Workflow.slug == slug))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{slug}' not found",
        )

    if not await can_user_access_workflow(db, user, workflow.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this workflow",
        )

    if not workflow.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This workflow is currently inactive",
        )

    # Parse input_data JSON
    try:
        parsed_input = json.loads(input_data)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="input_data must be valid JSON",
        )

    # Validate file size
    max_size_mb = settings.max_upload_size_mb
    recipe = workflow.recipe or {}
    file_config = recipe.get("file_config", {})
    if file_config.get("max_size_mb"):
        max_size_mb = min(max_size_mb, file_config["max_size_mb"])

    file_content = await file.read()
    file_size = len(file_content)
    if file_size > max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large: {file_size / 1024 / 1024:.1f} MB (max {max_size_mb} MB)",
        )

    # Save to temp file
    os.makedirs(settings.upload_temp_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    temp_filename = f"{uuid4()}{ext}"
    temp_path = os.path.join(settings.upload_temp_dir, temp_filename)

    wav_temp_path: str | None = None

    try:
        with open(temp_path, "wb") as f:
            f.write(file_content)

        # Validate minimum audio size (very short recordings produce invalid containers)
        actual_content_type = file.content_type or "application/octet-stream"
        actual_filename = file.filename or temp_filename
        is_audio_workflow = "audio" in (workflow.recipe or {}).get("collect", [])

        if is_audio_workflow and file_size < 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Recording too short ({file_size} bytes). Please record for at least 1-2 seconds.",
            )

        # Convert browser audio formats (webm/ogg) to WAV for whisper backends
        actual_path = temp_path

        if is_audio_workflow and actual_content_type not in NATIVE_AUDIO_TYPES:
            actual_path, actual_content_type, actual_filename = convert_audio_to_wav(
                temp_path, actual_content_type,
            )
            if actual_path != temp_path:
                wav_temp_path = actual_path

        # Build input data with file info
        exec_input = {
            "text": parsed_input.get("text", ""),
            "html": parsed_input.get("html", ""),
            "context": parsed_input.get("context", {}),
            "file_path": actual_path,
            "file_info": {
                "filename": actual_filename,
                "content_type": actual_content_type,
                "size_bytes": file_size,
            },
        }
        if parsed_input.get("clipboard"):
            exec_input["clipboard"] = parsed_input["clipboard"]
        if parsed_input.get("fields"):
            exec_input["fields"] = parsed_input["fields"]

        # Route to executor (same logic as execute_workflow)
        if workflow.workflow_type:
            output = await execute_http_workflow(
                workflow=workflow,
                input_data=exec_input,
                db=db,
                user_id=user.id,
                client_version=client_version,
                client_platform=client_platform,
                file_name=file.filename,
                file_size_bytes=file_size,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File upload requires a workflow with workflow_type set",
            )

        result_data = ExecutionResult(
            text=output.get("text"),
            action=output.get("action", "replace_selection"),
            success=output.get("success", True),
            error=output.get("error"),
            metadata=output.get("metadata", {}),
        )

        execution_log_id = output.get("execution_log_id")

        return ExecuteWorkflowResponse(
            execution_id=UUID(execution_log_id) if execution_log_id else workflow.id,
            status="success",
            result=result_data,
            duration_ms=output.get("duration_ms"),
        )

    except HTTPException:
        raise
    except AudioConversionError as e:
        return ExecuteWorkflowResponse(
            execution_id=uuid4(),
            status="error",
            result=ExecutionResult(
                text=None,
                action="none",
                success=False,
                error=e.message,
            ),
            duration_ms=None,
        )
    except HttpExecutionError as e:
        return ExecuteWorkflowResponse(
            execution_id=uuid4(),
            status="error",
            result=ExecutionResult(
                text=None,
                action="none",
                success=False,
                error=e.message,
            ),
            duration_ms=None,
        )
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        if wav_temp_path and os.path.exists(wav_temp_path):
            os.unlink(wav_temp_path)
