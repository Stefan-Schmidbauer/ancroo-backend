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
    llm_model_name = None
    if workflow.llm_model:
        llm_model_name = workflow.llm_model.name

    stt_model_name = None
    if workflow.stt_model:
        stt_model_name = workflow.stt_model.name

    tool_name = None
    if workflow.tool:
        tool_name = workflow.tool.name

    return WorkflowResponse(
        id=workflow.id,
        slug=workflow.slug,
        name=workflow.name,
        description=workflow.description,
        category=workflow.category_rel.name if workflow.category_rel else None,
        category_icon=workflow.category_rel.icon if workflow.category_rel else None,
        default_hotkey=workflow.default_hotkey,
        version=workflow.version,
        workflow_type=workflow.workflow_type,
        recipe=workflow.recipe,
        output_action=workflow.output_action,
        llm_model_name=llm_model_name,
        stt_model_name=stt_model_name,
        tool_name=tool_name,
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(user: CurrentUser, db: DbSession):
    """List all workflows the current user can access."""
    workflows = await get_accessible_workflows(db, user)

    return WorkflowListResponse(
        workflows=[workflow_to_response(w) for w in workflows],
        total=len(workflows),
        synced_at=datetime.now(timezone.utc),
    )


@router.get("/{slug}", response_model=WorkflowDetailResponse)
async def get_workflow(slug: str, user: CurrentUser, db: DbSession):
    """Get detailed information about a specific workflow."""
    result = await db.execute(
        select(Workflow)
        .options(
            selectinload(Workflow.category_rel),
            selectinload(Workflow.llm_model),
            selectinload(Workflow.stt_model),
            selectinload(Workflow.tool),
        )
        .where(Workflow.slug == slug)
    )
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

    llm_model_name = workflow.llm_model.name if workflow.llm_model else None
    stt_model_name = workflow.stt_model.name if workflow.stt_model else None
    tool_name = workflow.tool.name if workflow.tool else None

    return WorkflowDetailResponse(
        id=workflow.id,
        slug=workflow.slug,
        name=workflow.name,
        description=workflow.description,
        category=workflow.category_rel.name if workflow.category_rel else None,
        category_icon=workflow.category_rel.icon if workflow.category_rel else None,
        default_hotkey=workflow.default_hotkey,
        version=workflow.version,
        workflow_type=workflow.workflow_type,
        recipe=workflow.recipe,
        output_action=workflow.output_action,
        llm_model_name=llm_model_name,
        stt_model_name=stt_model_name,
        tool_name=tool_name,
        timeout_seconds=workflow.timeout_seconds,
        prompt_template=workflow.prompt_template,
        temperature=workflow.temperature,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.get("/sync/check")
async def check_workflow_updates(
    user: CurrentUser,
    db: DbSession,
    since: Optional[datetime] = None,
):
    """Check for workflow updates since a given timestamp."""
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
    """Get user's hotkey settings for all accessible workflows."""
    workflows = await get_accessible_workflows(db, user)

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
    """Update user's hotkey setting for a workflow."""
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
