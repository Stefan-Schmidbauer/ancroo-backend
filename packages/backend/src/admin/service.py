"""Admin service layer for workflow CRUD operations."""

from typing import Any, Optional
from uuid import UUID

from slugify import slugify
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import (
    Category,
    ExecutionLog,
    LLMModel,
    STTModel,
    Tool,
    Workflow,
    WorkflowPermission,
)


async def list_workflows(db: AsyncSession) -> list[Workflow]:
    """List all workflows ordered by name."""
    result = await db.execute(
        select(Workflow)
        .options(
            selectinload(Workflow.category_rel),
            selectinload(Workflow.llm_model),
            selectinload(Workflow.stt_model),
            selectinload(Workflow.tool),
        )
        .order_by(Workflow.name)
    )
    return list(result.scalars().all())


async def get_workflow(db: AsyncSession, slug: str) -> Optional[Workflow]:
    """Get a single workflow by slug, with relationships loaded."""
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
    category_id: Optional[UUID] = None,
    workflow_type: str = "tool",
    recipe: Optional[dict] = None,
    output_action: Optional[str] = None,
    default_hotkey: Optional[str] = None,
    timeout_seconds: int = 60,
    created_by: Optional[UUID] = None,
    # Execution target (exactly one)
    llm_model_id: Optional[UUID] = None,
    prompt_template: Optional[str] = None,
    temperature: Optional[float] = None,
    stt_model_id: Optional[UUID] = None,
    tool_id: Optional[UUID] = None,
) -> Workflow:
    """Create a new workflow."""
    slug = await _generate_unique_slug(db, name)

    workflow = Workflow(
        slug=slug,
        name=name,
        description=description,
        category_id=category_id,
        workflow_type=workflow_type,
        recipe=recipe,
        output_action=output_action,
        default_hotkey=default_hotkey,
        timeout_seconds=timeout_seconds,
        is_active=True,
        created_by=created_by,
        llm_model_id=llm_model_id,
        prompt_template=prompt_template,
        temperature=temperature,
        stt_model_id=stt_model_id,
        tool_id=tool_id,
    )
    db.add(workflow)
    await db.flush()

    # Auto-create default permissions
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
    category_id: Any = ...,
    workflow_type: Optional[str] = None,
    recipe: Optional[dict] = None,
    output_action: Optional[str] = None,
    default_hotkey: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    is_active: Optional[bool] = None,
    prompt_template: Optional[str] = None,
    temperature: Optional[float] = None,
    # Execution target (use Ellipsis sentinel to distinguish None from "not provided")
    llm_model_id: Any = ...,
    stt_model_id: Any = ...,
    tool_id: Any = ...,
) -> Optional[Workflow]:
    """Update an existing workflow. Only provided (non-None) fields are updated."""
    workflow = await get_workflow(db, slug)
    if not workflow:
        return None

    if name is not None:
        workflow.name = name
    if description is not None:
        workflow.description = description
    if category_id is not ...:
        workflow.category_id = category_id
    if workflow_type is not None:
        workflow.workflow_type = workflow_type
    if recipe is not None:
        workflow.recipe = recipe
    if output_action is not None:
        workflow.output_action = output_action
    if default_hotkey is not None:
        workflow.default_hotkey = default_hotkey
    if timeout_seconds is not None:
        workflow.timeout_seconds = timeout_seconds
    if is_active is not None:
        workflow.is_active = is_active
    if prompt_template is not None:
        workflow.prompt_template = prompt_template
    if temperature is not None:
        workflow.temperature = temperature
    if llm_model_id is not ...:
        workflow.llm_model_id = llm_model_id
    if stt_model_id is not ...:
        workflow.stt_model_id = stt_model_id
    if tool_id is not ...:
        workflow.tool_id = tool_id

    await db.flush()
    return workflow


async def duplicate_workflow(db: AsyncSession, slug: str) -> Optional[Workflow]:
    """Duplicate a workflow with a new name and slug."""
    source = await get_workflow(db, slug)
    if not source:
        return None

    new_name = f"{source.name} (Copy)"
    new_slug = await _generate_unique_slug(db, new_name)

    copy = Workflow(
        slug=new_slug,
        name=new_name,
        description=source.description,
        category_id=source.category_id,
        workflow_type=source.workflow_type,
        recipe=source.recipe,
        output_action=source.output_action,
        default_hotkey=None,  # Don't copy hotkey — must be unique
        timeout_seconds=source.timeout_seconds,
        is_active=False,  # Start inactive so admin can review
        created_by=source.created_by,
        llm_model_id=source.llm_model_id,
        prompt_template=source.prompt_template,
        temperature=source.temperature,
        stt_model_id=source.stt_model_id,
        tool_id=source.tool_id,
    )
    db.add(copy)
    await db.flush()

    # Copy default permissions
    for group in ["standard-users", "admin-users"]:
        db.add(WorkflowPermission(
            workflow_id=copy.id,
            group_name=group,
            permission_level="execute",
        ))
    await db.flush()

    return copy


async def duplicate_llm_model(db: AsyncSession, model_id: UUID) -> Optional[LLMModel]:
    """Duplicate an LLM model with a new name."""
    source = await db.get(LLMModel, model_id)
    if not source:
        return None

    copy = LLMModel(
        name=f"{source.name} (Copy)",
        provider_type=source.provider_type,
        base_url=source.base_url,
        endpoint_execute=source.endpoint_execute,
        endpoint_models=source.endpoint_models,
        api_key=source.api_key,  # Already encrypted
        model_id=source.model_id,
        default_temperature=source.default_temperature,
        config=source.config,
        is_active=False,  # Start inactive so admin can review
    )
    db.add(copy)
    await db.flush()

    return copy


async def duplicate_stt_model(db: AsyncSession, model_id: UUID) -> Optional[STTModel]:
    """Duplicate an STT model with a new name."""
    source = await db.get(STTModel, model_id)
    if not source:
        return None

    copy = STTModel(
        name=f"{source.name} (Copy)",
        provider_type=source.provider_type,
        base_url=source.base_url,
        api_key=source.api_key,
        model_id=source.model_id,
        default_language=source.default_language,
        config=source.config,
        is_active=False,
    )
    db.add(copy)
    await db.flush()

    return copy


async def delete_workflow(db: AsyncSession, slug: str) -> bool:
    """Delete a workflow by slug."""
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
    llm_models = await db.execute(select(func.count(LLMModel.id)))
    active_llm = await db.execute(
        select(func.count(LLMModel.id)).where(LLMModel.is_active == True)
    )
    stt_models = await db.execute(select(func.count(STTModel.id)))
    active_stt = await db.execute(
        select(func.count(STTModel.id)).where(STTModel.is_active == True)
    )
    tools = await db.execute(select(func.count(Tool.id)))
    active_tools = await db.execute(
        select(func.count(Tool.id)).where(Tool.is_active == True)
    )

    return {
        "total_workflows": total.scalar() or 0,
        "active_workflows": active.scalar() or 0,
        "total_executions": executions.scalar() or 0,
        "llm_models": llm_models.scalar() or 0,
        "active_llm_models": active_llm.scalar() or 0,
        "stt_models": stt_models.scalar() or 0,
        "active_stt_models": active_stt.scalar() or 0,
        "tools": tools.scalar() or 0,
        "active_tools": active_tools.scalar() or 0,
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


# --- Category CRUD ---


async def list_categories(db: AsyncSession) -> list[Category]:
    """List all categories ordered by name."""
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())


async def get_category(db: AsyncSession, category_id: UUID) -> Optional[Category]:
    """Get a single category by ID."""
    result = await db.execute(select(Category).where(Category.id == category_id))
    return result.scalar_one_or_none()


async def get_category_by_name(db: AsyncSession, name: str) -> Optional[Category]:
    """Get a category by name (case-insensitive)."""
    result = await db.execute(
        select(Category).where(func.lower(Category.name) == name.lower())
    )
    return result.scalar_one_or_none()


async def create_category(db: AsyncSession, name: str, icon: str = "\U0001f527") -> Category:
    """Create a new category."""
    category = Category(name=name, icon=icon)
    db.add(category)
    await db.flush()
    return category


async def update_category(
    db: AsyncSession, category_id: UUID, name: Optional[str] = None, icon: Optional[str] = None
) -> Optional[Category]:
    """Update a category."""
    category = await get_category(db, category_id)
    if not category:
        return None
    if name is not None:
        category.name = name
    if icon is not None:
        category.icon = icon
    await db.flush()
    return category


async def delete_category(db: AsyncSession, category_id: UUID) -> tuple[bool, str]:
    """Delete a category. Returns (success, message).

    Refuses deletion if workflows are still assigned.
    """
    category = await get_category(db, category_id)
    if not category:
        return False, "Category not found."

    # Check for assigned workflows
    count_result = await db.execute(
        select(func.count(Workflow.id)).where(Workflow.category_id == category_id)
    )
    count = count_result.scalar() or 0
    if count > 0:
        return False, f"Cannot delete: {count} workflow(s) still assigned to this category."

    await db.delete(category)
    await db.flush()
    return True, "Deleted."
