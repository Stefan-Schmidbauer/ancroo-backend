"""Tool provider registry — loads providers from DB and creates instances."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.crypto import decrypt_api_key
from src.db.models import ToolProvider as ToolProviderModel
from src.integrations.tool_provider import ToolProvider, ToolProviderError
from src.integrations.n8n import N8nProvider


# Map provider_type strings to their implementation classes
_PROVIDER_CLASSES: dict[str, type] = {
    "n8n": N8nProvider,
}


def _create_provider_instance(model: ToolProviderModel) -> ToolProvider:
    """Create a ToolProvider instance from a DB model."""
    cls = _PROVIDER_CLASSES.get(model.provider_type)
    if cls is None:
        raise ToolProviderError(
            f"Unknown provider type: {model.provider_type}. "
            f"Supported: {', '.join(_PROVIDER_CLASSES.keys())}"
        )

    kwargs: dict = {
        "base_url": model.base_url,
        "api_key": decrypt_api_key(model.api_key),
        "config": model.config or {},
    }

    return cls(**kwargs)


async def get_provider(db: AsyncSession, provider_id: UUID) -> ToolProvider:
    """Load a provider from DB and return a configured instance."""
    result = await db.execute(
        select(ToolProviderModel).where(ToolProviderModel.id == provider_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise ToolProviderError(f"Tool provider {provider_id} not found")
    if not model.is_active:
        raise ToolProviderError(f"Tool provider '{model.name}' is inactive")
    return _create_provider_instance(model)


async def get_provider_by_type(db: AsyncSession, provider_type: str) -> ToolProvider | None:
    """Find the first active provider of a given type."""
    result = await db.execute(
        select(ToolProviderModel).where(
            ToolProviderModel.provider_type == provider_type,
            ToolProviderModel.is_active == True,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        return None
    return _create_provider_instance(model)


async def get_provider_model(db: AsyncSession, provider_id: UUID) -> ToolProviderModel | None:
    """Get the raw DB model for a provider."""
    result = await db.execute(
        select(ToolProviderModel).where(ToolProviderModel.id == provider_id)
    )
    return result.scalar_one_or_none()


async def list_providers(db: AsyncSession) -> list[ToolProviderModel]:
    """List all registered tool providers."""
    result = await db.execute(
        select(ToolProviderModel)
        .options(selectinload(ToolProviderModel.workflows))
        .order_by(ToolProviderModel.name)
    )
    return list(result.scalars().all())


async def check_health(db: AsyncSession, provider_id: UUID) -> dict:
    """Run a health check on a provider and update DB status."""
    from datetime import datetime, timezone

    result = await db.execute(
        select(ToolProviderModel).where(ToolProviderModel.id == provider_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise ToolProviderError(f"Tool provider {provider_id} not found")

    provider = _create_provider_instance(model)
    health = await provider.health_check()

    model.health_status = "healthy" if health.get("healthy") else "unhealthy"
    model.last_health_check = datetime.now(timezone.utc)
    await db.flush()

    return health
