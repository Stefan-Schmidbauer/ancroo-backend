"""Admin API endpoints for LLM provider management."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.models import LLMProvider as LLMProviderModel, Workflow
from src.integrations.llm_provider import (
    LLMProviderError,
    check_provider_health,
    list_provider_models,
)
from src.api.v1.dependencies import CurrentUser, DbSession
from src.crypto import encrypt_api_key
from src.security import validate_provider_url

router = APIRouter(prefix="/admin/llm-providers", tags=["LLM Providers"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LLMProviderResponse(BaseModel):
    id: UUID
    provider_type: str
    name: str
    base_url: str
    api_key_set: bool
    default_model: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    health_status: str
    last_health_check: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, model: LLMProviderModel) -> "LLMProviderResponse":
        return cls(
            id=model.id,
            provider_type=model.provider_type,
            name=model.name,
            base_url=model.base_url,
            api_key_set=bool(model.api_key),
            default_model=model.default_model,
            config=model.config or {},
            is_active=model.is_active,
            health_status=model.health_status,
            last_health_check=model.last_health_check,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class LLMProviderListResponse(BaseModel):
    providers: list[LLMProviderResponse]
    total: int


class CreateLLMProviderRequest(BaseModel):
    provider_type: str = Field(
        ..., description="'ollama' or 'openai_compatible'"
    )
    name: str
    base_url: str
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class UpdateLLMProviderRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class WorkflowLLMAssignRequest(BaseModel):
    llm_provider_id: Optional[UUID] = Field(
        None, description="Provider ID to assign, or null to unassign"
    )
    llm_model: Optional[str] = Field(
        None, description="Model override; uses provider default when null"
    )


class WorkflowLLMAssignResponse(BaseModel):
    workflow_slug: str
    llm_provider_id: Optional[UUID]
    llm_model: Optional[str]
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


async def _get_provider_or_404(db: DbSession, provider_id: UUID) -> LLMProviderModel:
    model = await db.get(LLMProviderModel, provider_id)
    if model is None:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return model


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=LLMProviderListResponse)
async def list_llm_providers(user: CurrentUser, db: DbSession):
    """List all registered LLM providers."""
    result = await db.execute(
        select(LLMProviderModel).order_by(LLMProviderModel.name)
    )
    providers = list(result.scalars().all())
    return LLMProviderListResponse(
        providers=[LLMProviderResponse.from_model(p) for p in providers],
        total=len(providers),
    )


@router.post("", response_model=LLMProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_llm_provider(
    request: CreateLLMProviderRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Register a new LLM provider."""
    validate_provider_url(request.base_url)
    allowed_types = ("ollama", "openai_compatible")
    if request.provider_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"provider_type must be one of: {', '.join(allowed_types)}",
        )

    model = LLMProviderModel(
        provider_type=request.provider_type,
        name=request.name,
        base_url=request.base_url,
        api_key=encrypt_api_key(request.api_key) if request.api_key else None,
        default_model=request.default_model,
        config=request.config,
        is_active=request.is_active,
    )
    db.add(model)
    await db.flush()
    return LLMProviderResponse.from_model(model)


@router.get("/{provider_id}", response_model=LLMProviderResponse)
async def get_llm_provider(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Get a single LLM provider by ID."""
    model = await _get_provider_or_404(db, provider_id)
    return LLMProviderResponse.from_model(model)


@router.put("/{provider_id}", response_model=LLMProviderResponse)
async def update_llm_provider(
    provider_id: UUID,
    request: UpdateLLMProviderRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Update an LLM provider's configuration."""
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

    model.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return LLMProviderResponse.from_model(model)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_provider(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Delete an LLM provider.

    Workflows that reference this provider will have their llm_provider_id set
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
async def check_llm_provider_health(provider_id: UUID, user: CurrentUser, db: DbSession):
    """Run a health check against the LLM provider and update its status in the DB."""
    model = await _get_provider_or_404(db, provider_id)

    try:
        result = await check_provider_health(model)
    except LLMProviderError as e:
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
async def list_llm_provider_models(provider_id: UUID, user: CurrentUser, db: DbSession):
    """List models available from the LLM provider."""
    model = await _get_provider_or_404(db, provider_id)

    try:
        models = await list_provider_models(model)
    except LLMProviderError as e:
        raise HTTPException(status_code=502, detail=e.message)

    return ModelsResponse(
        provider_id=provider_id,
        provider_name=model.name,
        models=models,
        total=len(models),
    )


# ---------------------------------------------------------------------------
# Workflow ↔ LLM provider assignment
# (separate prefix so the URL reads /admin/llm-providers/workflows/{slug})
# ---------------------------------------------------------------------------

workflows_router = APIRouter(prefix="/admin/workflows", tags=["LLM Providers"])


@workflows_router.get("/{slug}/llm-provider", response_model=WorkflowLLMAssignResponse)
async def get_workflow_llm_provider(slug: str, user: CurrentUser, db: DbSession):
    """Get the LLM provider currently assigned to a workflow."""
    result = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.llm_provider))
        .where(Workflow.slug == slug)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    provider_name = workflow.llm_provider.name if workflow.llm_provider else None
    effective_model = (
        workflow.llm_model
        or (workflow.llm_provider.default_model if workflow.llm_provider else None)
    )

    return WorkflowLLMAssignResponse(
        workflow_slug=workflow.slug,
        llm_provider_id=workflow.llm_provider_id,
        llm_model=workflow.llm_model,
        provider_name=provider_name,
        effective_model=effective_model,
    )


@workflows_router.put("/{slug}/llm-provider", response_model=WorkflowLLMAssignResponse)
async def assign_workflow_llm_provider(
    slug: str,
    request: WorkflowLLMAssignRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Assign (or change) the LLM provider for a workflow.

    Set llm_provider_id to null to unassign (workflow reverts to baked-in
    target_config URL, if present).
    """
    result = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.llm_provider))
        .where(Workflow.slug == slug)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    if request.llm_provider_id is not None:
        # Validate provider exists
        provider = await db.get(LLMProviderModel, request.llm_provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="LLM provider not found")
        workflow.llm_provider_id = request.llm_provider_id
        workflow.llm_model = request.llm_model
        effective_model = request.llm_model or provider.default_model
        provider_name = provider.name
    else:
        workflow.llm_provider_id = None
        workflow.llm_model = None
        effective_model = None
        provider_name = None

    await db.flush()

    return WorkflowLLMAssignResponse(
        workflow_slug=workflow.slug,
        llm_provider_id=workflow.llm_provider_id,
        llm_model=workflow.llm_model,
        provider_name=provider_name,
        effective_model=effective_model,
    )


@workflows_router.delete(
    "/{slug}/llm-provider", status_code=status.HTTP_204_NO_CONTENT
)
async def unassign_workflow_llm_provider(slug: str, user: CurrentUser, db: DbSession):
    """Unassign the LLM provider from a workflow."""
    result = await db.execute(select(Workflow).where(Workflow.slug == slug))
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    workflow.llm_provider_id = None
    workflow.llm_model = None
    await db.flush()
