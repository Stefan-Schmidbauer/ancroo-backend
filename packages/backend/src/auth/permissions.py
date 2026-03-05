"""Permission checking for workflows.

When auth_enabled=false, all users have full access (development mode).
When auth_enabled=true, permissions are checked against WorkflowPermission.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.db.models import User, Workflow, WorkflowPermission


async def can_user_access_workflow(
    db: AsyncSession,
    user: User,
    workflow_id: UUID,
    required_level: str = "execute",
) -> bool:
    """Check if user can access a workflow at the required level."""
    settings = get_settings()
    if not settings.auth_enabled:
        return True

    if user.is_admin:
        return True

    result = await db.execute(
        select(WorkflowPermission).where(
            WorkflowPermission.workflow_id == workflow_id,
            (
                (WorkflowPermission.user_id == user.id)
                | (WorkflowPermission.group_name.in_(user.groups))
            ),
        ).limit(1)
    )
    return result.scalars().first() is not None


async def get_accessible_workflows(
    db: AsyncSession,
    user: User,
) -> list[Workflow]:
    """Return workflows accessible to the user."""
    load_opts = [
        selectinload(Workflow.tool_provider),
        selectinload(Workflow.llm_provider),
        selectinload(Workflow.stt_provider),
    ]
    settings = get_settings()
    if not settings.auth_enabled or user.is_admin:
        result = await db.execute(
            select(Workflow)
            .options(*load_opts)
            .where(Workflow.is_active == True)
        )
        return list(result.scalars().all())

    result = await db.execute(
        select(Workflow)
        .options(*load_opts)
        .join(WorkflowPermission, WorkflowPermission.workflow_id == Workflow.id)
        .where(
            Workflow.is_active == True,
            (
                (WorkflowPermission.user_id == user.id)
                | (WorkflowPermission.group_name.in_(user.groups))
            ),
        )
        .distinct()
    )
    return list(result.scalars().all())
