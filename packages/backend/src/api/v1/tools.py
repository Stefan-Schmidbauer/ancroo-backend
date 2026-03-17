"""Admin API endpoints for tool management (AR plugins, n8n webhooks, custom APIs)."""

from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from src.config import get_settings
from src.db.models import Tool
from src.integrations.runner import RunnerDiscoveryError, sync_tools_from_runner
from src.api.v1.schemas import (
    ToolResponse,
    ToolListResponse,
    HealthCheckResponse,
    RunnerSyncResponse,
)
from src.api.v1.dependencies import CurrentUser, DbSession

router = APIRouter(prefix="/admin/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
async def list_tools(user: CurrentUser, db: DbSession):
    """List all registered tools."""
    result = await db.execute(select(Tool).order_by(Tool.name))
    tools = result.scalars().all()
    return ToolListResponse(
        tools=[ToolResponse.model_validate(t) for t in tools],
        total=len(tools),
    )


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(tool_id: UUID, user: CurrentUser, db: DbSession):
    """Get a single tool by ID."""
    tool = await db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return ToolResponse.model_validate(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(tool_id: UUID, user: CurrentUser, db: DbSession):
    """Delete a tool. Linked workflows will have their tool_id set to NULL."""
    tool = await db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    await db.delete(tool)
    await db.flush()


@router.get("/{tool_id}/health", response_model=HealthCheckResponse)
async def check_tool_health(tool_id: UUID, user: CurrentUser, db: DbSession):
    """Run a health check on a tool's endpoint."""
    tool = await db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # For AR plugins, check the runner /health endpoint
            if tool.tool_type == "ar_plugin":
                # Extract base URL from endpoint_url (e.g. http://runner:8000/convert/... -> http://runner:8000)
                from urllib.parse import urlparse
                parsed = urlparse(tool.endpoint_url)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                response = await client.get(f"{base_url}/health")
            elif tool.tool_type == "n8n_webhook" and tool.n8n_base_url:
                response = await client.get(f"{tool.n8n_base_url.rstrip('/')}/healthz")
            else:
                # Custom API — try a HEAD or GET on the endpoint
                response = await client.head(tool.endpoint_url)

            healthy = response.status_code < 400

            tool.health_status = "healthy" if healthy else "unhealthy"
            tool.last_health_check = datetime.now(timezone.utc)
            await db.flush()

            return HealthCheckResponse(
                healthy=healthy,
                message="OK" if healthy else f"HTTP {response.status_code}",
            )
    except httpx.HTTPError as e:
        tool.health_status = "unhealthy"
        tool.last_health_check = datetime.now(timezone.utc)
        await db.flush()
        return HealthCheckResponse(healthy=False, message=str(e))


@router.post("/discover-runner", response_model=RunnerSyncResponse)
async def discover_runner_plugins(user: CurrentUser, db: DbSession):
    """Auto-discover AR plugins from ancroo-runner."""
    settings = get_settings()
    try:
        report = await sync_tools_from_runner(db, settings.runner_base_url)
        return RunnerSyncResponse(**report)
    except RunnerDiscoveryError as e:
        raise HTTPException(status_code=502, detail=e.message)
