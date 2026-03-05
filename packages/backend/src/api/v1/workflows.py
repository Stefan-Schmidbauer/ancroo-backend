"""Workflow API endpoints."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.models import Workflow, UserHotkeySetting
from src.auth.permissions import get_accessible_workflows, can_user_access_workflow
from src.api.v1.schemas import (
    WorkflowResponse,
    WorkflowListResponse,
    WorkflowDetailResponse,
    HotkeySettingResponse,
    UpdateHotkeyRequest,
)
from src.api.v1.dependencies import CurrentUser, DbSession

router = APIRouter(prefix="/workflows", tags=["workflows"])


def workflow_to_response(workflow: Workflow) -> WorkflowResponse:
    """Convert workflow model to response schema."""
    provider_name = None
    if workflow.execution_type == "tool" and workflow.tool_provider:
        provider_name = workflow.tool_provider.name

    llm_provider_name = None
    if workflow.llm_provider:
        llm_provider_name = workflow.llm_provider.name

    stt_provider_name = None
    if workflow.stt_provider:
        stt_provider_name = workflow.stt_provider.name

    return WorkflowResponse(
        id=workflow.id,
        slug=workflow.slug,
        name=workflow.name,
        description=workflow.description,
        category=workflow.category,
        default_hotkey=workflow.default_hotkey,
        input_type=workflow.input_type,
        output_type=workflow.output_type,
        execution_type=workflow.execution_type,
        version=workflow.version,
        provider_name=provider_name,
        llm_provider_name=llm_provider_name,
        stt_provider_name=stt_provider_name,
        sync_status=workflow.sync_status,
        # New generic fields (public)
        workflow_type=workflow.workflow_type,
        recipe=workflow.recipe,
        output_action=workflow.output_action,
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(user: CurrentUser, db: DbSession):
    """List all workflows the current user can access.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        List of accessible workflows
    """
    workflows = await get_accessible_workflows(db, user)

    return WorkflowListResponse(
        workflows=[workflow_to_response(w) for w in workflows],
        total=len(workflows),
        synced_at=datetime.now(timezone.utc),
    )


@router.get("/{slug}", response_model=WorkflowDetailResponse)
async def get_workflow(slug: str, user: CurrentUser, db: DbSession):
    """Get detailed information about a specific workflow.

    Args:
        slug: Workflow slug identifier
        user: Current authenticated user
        db: Database session

    Returns:
        Workflow details
    """
    # Find workflow by slug (eager-load providers to avoid lazy-loading in async)
    result = await db.execute(
        select(Workflow)
        .options(
            selectinload(Workflow.tool_provider),
            selectinload(Workflow.llm_provider),
            selectinload(Workflow.stt_provider),
        )
        .where(Workflow.slug == slug)
    )
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

    provider_name = None
    if workflow.execution_type == "tool" and workflow.tool_provider:
        provider_name = workflow.tool_provider.name

    llm_provider_name = None
    if workflow.llm_provider:
        llm_provider_name = workflow.llm_provider.name

    stt_provider_name = None
    if workflow.stt_provider:
        stt_provider_name = workflow.stt_provider.name

    return WorkflowDetailResponse(
        id=workflow.id,
        slug=workflow.slug,
        name=workflow.name,
        description=workflow.description,
        category=workflow.category,
        default_hotkey=workflow.default_hotkey,
        input_type=workflow.input_type,
        output_type=workflow.output_type,
        execution_type=workflow.execution_type,
        version=workflow.version,
        provider_name=provider_name,
        llm_provider_name=llm_provider_name,
        stt_provider_name=stt_provider_name,
        sync_status=workflow.sync_status,
        workflow_type=workflow.workflow_type,
        recipe=workflow.recipe,
        output_action=workflow.output_action,
        timeout_seconds=workflow.timeout_seconds,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.get("/sync/check")
async def check_workflow_updates(
    user: CurrentUser,
    db: DbSession,
    since: Optional[datetime] = None,
):
    """Check for workflow updates since a given timestamp.

    Used by client to sync workflows incrementally.

    Args:
        user: Current authenticated user
        db: Database session
        since: Timestamp to check updates from

    Returns:
        List of updated workflows
    """
    workflows = await get_accessible_workflows(db, user)

    if since:
        workflows = [w for w in workflows if w.updated_at > since]

    return {
        "workflows": [workflow_to_response(w) for w in workflows],
        "total": len(workflows),
        "synced_at": datetime.now(timezone.utc),
    }


@router.get("/hotkeys/settings", response_model=list[HotkeySettingResponse])
async def get_hotkey_settings(user: CurrentUser, db: DbSession):
    """Get user's hotkey settings for all accessible workflows.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        List of hotkey settings
    """
    workflows = await get_accessible_workflows(db, user)

    # Get user's custom hotkey settings
    result = await db.execute(
        select(UserHotkeySetting).where(UserHotkeySetting.user_id == user.id)
    )
    settings_map = {s.workflow_id: s for s in result.scalars().all()}

    hotkey_settings = []
    for workflow in workflows:
        custom_setting = settings_map.get(workflow.id)

        hotkey_settings.append(
            HotkeySettingResponse(
                workflow_id=workflow.id,
                workflow_slug=workflow.slug,
                workflow_name=workflow.name,
                hotkey=custom_setting.custom_hotkey
                if custom_setting and custom_setting.custom_hotkey
                else workflow.default_hotkey or "",
                is_enabled=custom_setting.is_enabled if custom_setting else True,
            )
        )

    return hotkey_settings


@router.put("/hotkeys/settings")
async def update_hotkey_setting(
    request: UpdateHotkeyRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Update user's hotkey setting for a workflow.

    Args:
        request: Hotkey update request
        user: Current authenticated user
        db: Database session

    Returns:
        Updated hotkey setting
    """
    # Verify workflow exists and user has access
    result = await db.execute(
        select(Workflow).where(Workflow.id == request.workflow_id)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if not await can_user_access_workflow(db, user, workflow.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this workflow",
        )

    # Find or create hotkey setting
    result = await db.execute(
        select(UserHotkeySetting).where(
            UserHotkeySetting.user_id == user.id,
            UserHotkeySetting.workflow_id == request.workflow_id,
        )
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.custom_hotkey = request.custom_hotkey
        setting.is_enabled = request.is_enabled
        setting.updated_at = datetime.now(timezone.utc)
    else:
        setting = UserHotkeySetting(
            user_id=user.id,
            workflow_id=request.workflow_id,
            custom_hotkey=request.custom_hotkey,
            is_enabled=request.is_enabled,
        )
        db.add(setting)

    await db.flush()

    return HotkeySettingResponse(
        workflow_id=workflow.id,
        workflow_slug=workflow.slug,
        workflow_name=workflow.name,
        hotkey=setting.custom_hotkey or workflow.default_hotkey or "",
        is_enabled=setting.is_enabled,
    )
