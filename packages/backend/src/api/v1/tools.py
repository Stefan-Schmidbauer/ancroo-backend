"""Admin API endpoints for tool provider management."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from src.db.models import ToolProvider as ToolProviderModel, Workflow
from src.integrations import registry, sync
from src.integrations.tool_provider import ToolProviderError
from src.api.v1.schemas import (
    ToolProviderResponse,
    ToolProviderListResponse,
    CreateToolProviderRequest,
    UpdateToolProviderRequest,
    DiscoveredFlowResponse,
    DiscoverFlowsResponse,
    ImportFlowRequest,
    SyncResultResponse,
    HealthCheckResponse,
)
from src.api.v1.dependencies import CurrentUser, DbSession
from src.crypto import encrypt_api_key
from src.security import validate_provider_url

router = APIRouter(prefix="/admin/tools", tags=["tools"])


@router.get("", response_model=ToolProviderListResponse)
async def list_tool_providers(user: CurrentUser, db: DbSession):
    """List all registered tool providers."""
    providers = await registry.list_providers(db)
    return ToolProviderListResponse(
        providers=[ToolProviderResponse.model_validate(p) for p in providers],
        total=len(providers),
    )


@router.post("", response_model=ToolProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_tool_provider(
    request: CreateToolProviderRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Register a new tool provider."""
    validate_provider_url(request.base_url)
    provider = ToolProviderModel(
        provider_type=request.provider_type,
        name=request.name,
        base_url=request.base_url,
        api_key=encrypt_api_key(request.api_key) if request.api_key else None,
        config=request.config,
    )
    db.add(provider)
    await db.flush()
    return ToolProviderResponse.model_validate(provider)


@router.get("/{provider_id}", response_model=ToolProviderResponse)
async def get_tool_provider(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Get a single tool provider by ID."""
    model = await registry.get_provider_model(db, provider_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Tool provider not found")
    return ToolProviderResponse.model_validate(model)


@router.put("/{provider_id}", response_model=ToolProviderResponse)
async def update_tool_provider(
    provider_id: UUID,
    request: UpdateToolProviderRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Update a tool provider's configuration."""
    model = await registry.get_provider_model(db, provider_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    if request.name is not None:
        model.name = request.name
    if request.base_url is not None:
        validate_provider_url(request.base_url)
        model.base_url = request.base_url
    if request.api_key is not None:
        model.api_key = encrypt_api_key(request.api_key) if request.api_key else None
    if request.config is not None:
        model.config = request.config
    if request.is_active is not None:
        model.is_active = request.is_active

    await db.flush()
    return ToolProviderResponse.model_validate(model)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool_provider(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Delete a tool provider. Linked workflows will have their provider set to NULL."""
    model = await registry.get_provider_model(db, provider_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    await db.delete(model)
    await db.flush()


@router.get("/{provider_id}/health", response_model=HealthCheckResponse)
async def check_provider_health(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Run a health check on a tool provider."""
    try:
        result = await registry.check_health(db, provider_id)
        return HealthCheckResponse(
            healthy=result.get("healthy", False),
            message=result.get("message", ""),
            details={k: v for k, v in result.items() if k not in ("healthy", "message")},
        )
    except ToolProviderError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/{provider_id}/flows", response_model=DiscoverFlowsResponse)
async def discover_provider_flows(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Discover available flows from a tool provider."""
    model = await registry.get_provider_model(db, provider_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    try:
        flows = await sync.discover_flows(db, provider_id)
    except ToolProviderError as e:
        raise HTTPException(status_code=502, detail=e.message)

    # Check which flows are already imported
    existing = await db.execute(
        select(Workflow.external_flow_id).where(
            Workflow.tool_provider_id == provider_id,
            Workflow.execution_type == "tool",
        )
    )
    imported_ids = {row[0] for row in existing.all()}

    return DiscoverFlowsResponse(
        provider_id=provider_id,
        provider_name=model.name,
        flows=[
            DiscoveredFlowResponse(
                id=f["id"],
                name=f.get("name", f["id"]),
                description=f.get("description", ""),
                status=f.get("status", "ENABLED"),
                trigger_type=f.get("trigger_type", ""),
                has_webhook=f.get("has_webhook", False),
                already_imported=f["id"] in imported_ids,
            )
            for f in flows
        ],
        total=len(flows),
    )


@router.post("/{provider_id}/flows/import", response_model=dict)
async def import_provider_flow(
    provider_id: UUID,
    request: ImportFlowRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Import a discovered flow as an Ancroo workflow."""
    try:
        workflow = await sync.import_flow(
            db=db,
            provider_id=provider_id,
            flow_data={"id": request.flow_id, "name": request.flow_name},
            category=request.category,
            input_type=request.input_type,
            output_type=request.output_type,
        )
        return {
            "workflow_id": str(workflow.id),
            "workflow_slug": workflow.slug,
            "message": f"Flow '{request.flow_name}' imported as workflow '{workflow.slug}'",
        }
    except ToolProviderError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/{provider_id}/sync", response_model=SyncResultResponse)
async def sync_provider_workflows(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Sync all workflows linked to a provider with its current flows."""
    model = await registry.get_provider_model(db, provider_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    try:
        report = await sync.sync_workflows(db, provider_id)
        return SyncResultResponse(**report)
    except ToolProviderError as e:
        raise HTTPException(status_code=502, detail=e.message)
