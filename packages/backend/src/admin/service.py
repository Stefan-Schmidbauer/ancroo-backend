"""Admin service layer for workflow CRUD operations."""

import json
from typing import Any, Optional
from uuid import UUID

from slugify import slugify
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Workflow, ExecutionLog, ToolProvider, WorkflowPermission


async def list_workflows(db: AsyncSession) -> list[Workflow]:
    """List all workflows ordered by name."""
    result = await db.execute(
        select(Workflow)
        .options(
            selectinload(Workflow.tool_provider),
            selectinload(Workflow.llm_provider),
            selectinload(Workflow.stt_provider),
        )
        .order_by(Workflow.name)
    )
    return list(result.scalars().all())


async def get_workflow(db: AsyncSession, slug: str) -> Optional[Workflow]:
    """Get a single workflow by slug, with provider relationships loaded."""
    result = await db.execute(
        select(Workflow)
        .options(
            selectinload(Workflow.tool_provider),
            selectinload(Workflow.llm_provider),
            selectinload(Workflow.stt_provider),
        )
        .where(Workflow.slug == slug)
    )
    return result.scalar_one_or_none()


async def _generate_unique_slug(db: AsyncSession, name: str) -> str:
    """Generate a unique slug from a workflow name."""
    slug = slugify(name)
    existing = await get_workflow(db, slug)
    if not existing:
        return slug
    counter = 2
    while True:
        candidate = f"{slug}-{counter}"
        if not await get_workflow(db, candidate):
            return candidate
        counter += 1


async def create_workflow(
    db: AsyncSession,
    name: str,
    description: str = "",
    category: str = "text",
    output_type: str = "replace_selection",
    pipeline_steps: list[dict[str, Any]] | None = None,
    created_by: Optional[UUID] = None,
    # New generic fields
    workflow_type: Optional[str] = None,
    recipe: Optional[dict] = None,
    target_config: Optional[dict] = None,
    output_action: Optional[str] = None,
    default_hotkey: Optional[str] = None,
    # Provider assignments
    llm_provider_id: Optional[UUID] = None,
    llm_model: Optional[str] = None,
    stt_provider_id: Optional[UUID] = None,
    stt_model: Optional[str] = None,
) -> Workflow:
    """Create a new workflow.

    Supports both legacy pipeline workflows and new generic HTTP workflows.
    """
    slug = await _generate_unique_slug(db, name)

    # Derive execution_type from workflow_type
    if not workflow_type:
        exec_type = "pipeline"
    elif workflow_type in ("workflow_trigger", "custom"):
        exec_type = "tool"
    else:
        exec_type = "script"

    workflow = Workflow(
        slug=slug,
        name=name,
        description=description,
        category=category,
        execution_type=exec_type,
        output_type=output_type,
        pipeline_steps=pipeline_steps or [],
        is_active=True,
        created_by=created_by,
        # New generic fields
        workflow_type=workflow_type,
        recipe=recipe,
        target_config=target_config,
        output_action=output_action,
        default_hotkey=default_hotkey,
        # Provider assignments
        llm_provider_id=llm_provider_id,
        llm_model=llm_model,
        stt_provider_id=stt_provider_id,
        stt_model=stt_model,
    )
    db.add(workflow)
    await db.flush()

    # Auto-create default permissions so the workflow is visible to all users
    for group in ["standard-users", "admin-users"]:
        db.add(WorkflowPermission(
            workflow_id=workflow.id,
            group_name=group,
            permission_level="execute",
        ))
    await db.flush()

    return workflow


async def update_workflow(
    db: AsyncSession,
    slug: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    output_type: Optional[str] = None,
    pipeline_steps: Optional[list[dict[str, Any]]] = None,
    is_active: Optional[bool] = None,
    # New generic fields
    workflow_type: Optional[str] = None,
    recipe: Optional[dict] = None,
    target_config: Optional[dict] = None,
    output_action: Optional[str] = None,
    default_hotkey: Optional[str] = None,
    # Provider assignments (use _UNSET sentinel to distinguish None from "not provided")
    llm_provider_id: Any = ...,
    llm_model: Any = ...,
    stt_provider_id: Any = ...,
    stt_model: Any = ...,
) -> Optional[Workflow]:
    """Update an existing workflow.

    Only provided (non-None) fields are updated.
    Provider fields use Ellipsis (...) as sentinel to distinguish "not provided"
    from "set to None" (unassign).
    """
    workflow = await get_workflow(db, slug)
    if not workflow:
        return None

    if name is not None:
        workflow.name = name
    if description is not None:
        workflow.description = description
    if category is not None:
        workflow.category = category
    if output_type is not None:
        workflow.output_type = output_type
    if pipeline_steps is not None:
        workflow.pipeline_steps = pipeline_steps
    if is_active is not None:
        workflow.is_active = is_active
    if workflow_type is not None:
        workflow.workflow_type = workflow_type
    if recipe is not None:
        workflow.recipe = recipe
    if target_config is not None:
        workflow.target_config = target_config
    if output_action is not None:
        workflow.output_action = output_action
    if default_hotkey is not None:
        workflow.default_hotkey = default_hotkey
    if llm_provider_id is not ...:
        workflow.llm_provider_id = llm_provider_id
    if llm_model is not ...:
        workflow.llm_model = llm_model
    if stt_provider_id is not ...:
        workflow.stt_provider_id = stt_provider_id
    if stt_model is not ...:
        workflow.stt_model = stt_model

    await db.flush()
    return workflow


async def delete_workflow(db: AsyncSession, slug: str) -> bool:
    """Delete a workflow by slug.

    Returns:
        True if deleted, False if not found.
    """
    workflow = await get_workflow(db, slug)
    if not workflow:
        return False

    await db.delete(workflow)
    await db.flush()
    return True


async def get_workflow_stats(db: AsyncSession) -> dict[str, Any]:
    """Get aggregate stats for the dashboard."""
    total = await db.execute(select(func.count(Workflow.id)))
    active = await db.execute(
        select(func.count(Workflow.id)).where(Workflow.is_active == True)
    )
    executions = await db.execute(select(func.count(ExecutionLog.id)))
    providers = await db.execute(select(func.count(ToolProvider.id)))

    return {
        "total_workflows": total.scalar() or 0,
        "active_workflows": active.scalar() or 0,
        "total_executions": executions.scalar() or 0,
        "tool_providers": providers.scalar() or 0,
    }


async def get_recent_executions(
    db: AsyncSession, workflow_id: UUID, limit: int = 10
) -> list[ExecutionLog]:
    """Get recent execution logs for a workflow."""
    result = await db.execute(
        select(ExecutionLog)
        .where(ExecutionLog.workflow_id == workflow_id)
        .order_by(desc(ExecutionLog.started_at))
        .limit(limit)
    )
    return list(result.scalars().all())
