"""Admin API endpoints for STT provider management."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from src.db.models import STTProvider as STTProviderModel, Workflow
from src.integrations.stt_provider import (
    STTProviderError,
    check_provider_health,
    list_provider_models,
)
from src.api.v1.dependencies import CurrentUser, DbSession
from src.crypto import encrypt_api_key
from src.security import validate_provider_url

router = APIRouter(prefix="/admin/stt-providers", tags=["STT Providers"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class STTProviderResponse(BaseModel):
    id: UUID
    provider_type: str
    name: str
    base_url: str
    api_key_set: bool
    default_model: str
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    is_default: bool
    health_status: str
    last_health_check: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, model: STTProviderModel) -> "STTProviderResponse":
        return cls(
            id=model.id,
            provider_type=model.provider_type,
            name=model.name,
            base_url=model.base_url,
            api_key_set=bool(model.api_key),
            default_model=model.default_model,
            config=model.config or {},
            is_active=model.is_active,
            is_default=model.is_default,
            health_status=model.health_status,
            last_health_check=model.last_health_check,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class STTProviderListResponse(BaseModel):
    providers: list[STTProviderResponse]
    total: int


class CreateSTTProviderRequest(BaseModel):
    provider_type: str = Field(
        ..., description="'whisper_openai_compatible'"
    )
    name: str
    base_url: str
    api_key: Optional[str] = None
    default_model: str
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    is_default: bool = False


class UpdateSTTProviderRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class WorkflowSTTAssignRequest(BaseModel):
    stt_provider_id: Optional[UUID] = Field(
        None, description="Provider ID to assign, or null to unassign"
    )
    stt_model: Optional[str] = Field(
        None, description="Model override; uses provider default when null"
    )


class WorkflowSTTAssignResponse(BaseModel):
    workflow_slug: str
    stt_provider_id: Optional[UUID]
    stt_model: Optional[str]
    provider_name: Optional[str]
    effective_model: Optional[str]


class HealthCheckResponse(BaseModel):
    healthy: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ModelsResponse(BaseModel):
    provider_id: UUID
    provider_name: str
    models: list[str]
    total: int


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_provider_or_404(db: DbSession, provider_id: UUID) -> STTProviderModel:
    model = await db.get(STTProviderModel, provider_id)
    if model is None:
        raise HTTPException(status_code=404, detail="STT provider not found")
    return model


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=STTProviderListResponse)
async def list_stt_providers(user: CurrentUser, db: DbSession):
    """List all registered STT providers."""
    result = await db.execute(
        select(STTProviderModel).order_by(STTProviderModel.name)
    )
    providers = list(result.scalars().all())
    return STTProviderListResponse(
        providers=[STTProviderResponse.from_model(p) for p in providers],
        total=len(providers),
    )


@router.post("", response_model=STTProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_stt_provider(
    request: CreateSTTProviderRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Register a new STT provider."""
    validate_provider_url(request.base_url)
    allowed_types = ("whisper_openai_compatible",)
    if request.provider_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"provider_type must be one of: {', '.join(allowed_types)}",
        )

    # If this provider is set as default, unset all others first
    if request.is_default:
        await db.execute(
            update(STTProviderModel).values(is_default=False)
        )

    model = STTProviderModel(
        provider_type=request.provider_type,
        name=request.name,
        base_url=request.base_url,
        api_key=encrypt_api_key(request.api_key) if request.api_key else None,
        default_model=request.default_model,
        config=request.config,
        is_active=request.is_active,
        is_default=request.is_default,
    )
    db.add(model)
    await db.flush()
    return STTProviderResponse.from_model(model)


@router.get("/{provider_id}", response_model=STTProviderResponse)
async def get_stt_provider(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Get a single STT provider by ID."""
    model = await _get_provider_or_404(db, provider_id)
    return STTProviderResponse.from_model(model)


@router.put("/{provider_id}", response_model=STTProviderResponse)
async def update_stt_provider(
    provider_id: UUID,
    request: UpdateSTTProviderRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Update an STT provider's configuration."""
    model = await _get_provider_or_404(db, provider_id)

    if request.name is not None:
        model.name = request.name
    if request.base_url is not None:
        validate_provider_url(request.base_url)
        model.base_url = request.base_url
    if request.api_key is not None:
        model.api_key = encrypt_api_key(request.api_key) if request.api_key else None
    if request.default_model is not None:
        model.default_model = request.default_model
    if request.config is not None:
        model.config = request.config
    if request.is_active is not None:
        model.is_active = request.is_active
    if request.is_default is not None:
        if request.is_default:
            # Unset all others before setting this one as default
            await db.execute(
                update(STTProviderModel).values(is_default=False)
            )
        model.is_default = request.is_default

    model.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return STTProviderResponse.from_model(model)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stt_provider(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Delete an STT provider.

    Workflows that reference this provider will have their stt_provider_id set
    to NULL (ON DELETE SET NULL in DB). They will fall back to baked-in
    target_config URL if present, or fail execution.
    """
    model = await _get_provider_or_404(db, provider_id)
    await db.delete(model)
    await db.flush()


# ---------------------------------------------------------------------------
# Health check + model listing
# ---------------------------------------------------------------------------


@router.get("/{provider_id}/health", response_model=HealthCheckResponse)
async def check_stt_provider_health(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Run a health check against the STT provider and update its status in the DB."""
    model = await _get_provider_or_404(db, provider_id)

    try:
        result = await check_provider_health(model)
    except STTProviderError as e:
        raise HTTPException(status_code=502, detail=e.message)

    model.health_status = "healthy" if result.get("healthy") else "unhealthy"
    model.last_health_check = datetime.now(timezone.utc)
    await db.flush()

    return HealthCheckResponse(
        healthy=result.get("healthy", False),
        message=result.get("error", ""),
        details={k: v for k, v in result.items() if k not in ("healthy", "error")},
    )


@router.get("/{provider_id}/models", response_model=ModelsResponse)
async def list_stt_provider_models(provider_id: UUID, user: CurrentUser, db: DbSession):
    """List models available from the STT provider."""
    model = await _get_provider_or_404(db, provider_id)

    try:
        models = await list_provider_models(model)
    except STTProviderError as e:
        raise HTTPException(status_code=502, detail=e.message)

    return ModelsResponse(
        provider_id=provider_id,
        provider_name=model.name,
        models=models,
        total=len(models),
    )


# ---------------------------------------------------------------------------
# Workflow ↔ STT provider assignment
# ---------------------------------------------------------------------------

workflows_router = APIRouter(prefix="/admin/workflows", tags=["STT Providers"])


@workflows_router.get("/{slug}/stt-provider", response_model=WorkflowSTTAssignResponse)
async def get_workflow_stt_provider(slug: str, user: CurrentUser, db: DbSession):
    """Get the STT provider currently assigned to a workflow."""
    result = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.stt_provider))
        .where(Workflow.slug == slug)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    provider_name = workflow.stt_provider.name if workflow.stt_provider else None
    effective_model = (
        workflow.stt_model
        or (workflow.stt_provider.default_model if workflow.stt_provider else None)
    )

    return WorkflowSTTAssignResponse(
        workflow_slug=workflow.slug,
        stt_provider_id=workflow.stt_provider_id,
        stt_model=workflow.stt_model,
        provider_name=provider_name,
        effective_model=effective_model,
    )


@workflows_router.put("/{slug}/stt-provider", response_model=WorkflowSTTAssignResponse)
async def assign_workflow_stt_provider(
    slug: str,
    request: WorkflowSTTAssignRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Assign (or change) the STT provider for a workflow.

    Set stt_provider_id to null to unassign (workflow reverts to baked-in
    target_config URL, if present).
    """
    result = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.stt_provider))
        .where(Workflow.slug == slug)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    if request.stt_provider_id is not None:
        # Validate provider exists
        provider = await db.get(STTProviderModel, request.stt_provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="STT provider not found")
        workflow.stt_provider_id = request.stt_provider_id
        workflow.stt_model = request.stt_model
        effective_model = request.stt_model or provider.default_model
        provider_name = provider.name
    else:
        workflow.stt_provider_id = None
        workflow.stt_model = None
        effective_model = None
        provider_name = None

    await db.flush()

    return WorkflowSTTAssignResponse(
        workflow_slug=workflow.slug,
        stt_provider_id=workflow.stt_provider_id,
        stt_model=workflow.stt_model,
        provider_name=provider_name,
        effective_model=effective_model,
    )


@workflows_router.delete(
    "/{slug}/stt-provider", status_code=status.HTTP_204_NO_CONTENT
)
async def unassign_workflow_stt_provider(slug: str, user: CurrentUser, db: DbSession):
    """Unassign the STT provider from a workflow."""
    result = await db.execute(select(Workflow).where(Workflow.slug == slug))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    workflow.stt_provider_id = None
    workflow.stt_model = None
    await db.flush()
