"""Flow discovery and sync between external tool providers and Ancroo workflows."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ToolProvider as ToolProviderModel, Workflow
from src.integrations.registry import get_provider, get_provider_model
from src.integrations.tool_provider import ToolProviderError


async def discover_flows(db: AsyncSession, provider_id: UUID) -> list[dict[str, Any]]:
    """Discover available flows from a tool provider.

    Returns raw flow data from the provider's API.
    """
    provider = await get_provider(db, provider_id)
    return await provider.discover_flows()


async def import_flow(
    db: AsyncSession,
    provider_id: UUID,
    flow_data: dict[str, Any],
    category: str = "tool",
    input_type: str = "text_selection",
    output_type: str = "clipboard",
) -> Workflow:
    """Import a single external flow as an Ancroo workflow.

    Creates a workflow with execution_type='tool' that delegates to the provider.

    Args:
        db: Database session
        provider_id: The tool provider ID
        flow_data: Flow data from discover_flows() with at least 'id' and 'name'
        category: Workflow category
        input_type: Expected input type
        output_type: Expected output type

    Returns:
        Created Workflow instance
    """
    provider_model = await get_provider_model(db, provider_id)
    if provider_model is None:
        raise ToolProviderError(f"Tool provider {provider_id} not found")

    flow_name = flow_data.get("name", flow_data.get("id", "Unknown Flow"))
    slug = slugify(flow_name)

    # Ensure unique slug
    existing = await db.execute(select(Workflow).where(Workflow.slug == slug))
    if existing.scalar_one_or_none():
        counter = 2
        while True:
            candidate = f"{slug}-{counter}"
            check = await db.execute(select(Workflow).where(Workflow.slug == candidate))
            if not check.scalar_one_or_none():
                slug = candidate
                break
            counter += 1

    workflow = Workflow(
        slug=slug,
        name=flow_name,
        description=flow_data.get("description", ""),
        category=category,
        execution_type="tool",
        tool_provider_id=provider_id,
        external_flow_id=flow_data["id"],
        input_type=input_type,
        output_type=output_type,
        sync_status="synced",
        last_synced_at=datetime.now(timezone.utc),
        is_active=flow_data.get("status", "ENABLED") == "ENABLED",
    )
    db.add(workflow)
    await db.flush()
    return workflow


async def sync_workflows(db: AsyncSession, provider_id: UUID) -> dict[str, Any]:
    """Synchronize all tool-delegated workflows for a provider.

    Checks which external flows still exist, updates metadata,
    and marks missing flows.

    Returns:
        Sync report with counts of synced, stale, missing workflows.
    """
    provider = await get_provider(db, provider_id)
    external_flows = await provider.discover_flows()
    external_flow_ids = {f["id"] for f in external_flows}
    external_flow_map = {f["id"]: f for f in external_flows}

    # Get all Ancroo workflows linked to this provider
    result = await db.execute(
        select(Workflow).where(
            Workflow.tool_provider_id == provider_id,
            Workflow.execution_type == "tool",
        )
    )
    workflows = list(result.scalars().all())

    report = {"synced": 0, "updated": 0, "missing": 0, "total": len(workflows)}

    now = datetime.now(timezone.utc)
    for wf in workflows:
        if wf.external_flow_id in external_flow_ids:
            flow_data = external_flow_map[wf.external_flow_id]
            new_name = flow_data.get("name", wf.name)
            new_desc = flow_data.get("description", wf.description)

            if wf.name != new_name or wf.description != new_desc:
                wf.name = new_name
                wf.description = new_desc
                report["updated"] += 1

            wf.sync_status = "synced"
            wf.last_synced_at = now
            report["synced"] += 1
        else:
            wf.sync_status = "missing"
            wf.last_synced_at = now
            report["missing"] += 1

    await db.flush()
    return report
