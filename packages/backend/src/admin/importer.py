"""Workflow import from JSON definitions.

Accepts a workflow JSON (the metadata.json format) and creates the
corresponding database records: providers (find-or-create), workflow,
and permissions.  For workflows that require n8n, webhook flow
provisioning is attempted with a short health-check timeout.

Used by:
- Admin UI file upload (POST /admin/import)
- API endpoint (POST /admin/api/import-workflow)
- Install script (curl with JSON body)
"""

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.models import (
    LLMProvider,
    STTProvider,
    ToolProvider,
    Workflow,
    WorkflowPermission,
)
from src.execution.presets import (
    build_llm_target,
    build_n8n_target,
    build_recipe,
    build_stt_target,
    build_whisper_target,
)

logger = logging.getLogger(__name__)

# n8n readiness check — short timeout (n8n starts fast, no piece sync)
_N8N_CHECK_TIMEOUT = 15.0


@dataclass
class ImportResult:
    status: str  # "created", "already_exists", "created_inactive", "reprovisioned", "error"
    slug: str = ""
    name: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        d = {"status": self.status}
        if self.slug:
            d["slug"] = self.slug
        if self.name:
            d["name"] = self.name
        if self.message:
            d["message"] = self.message
        return d


# ---------------------------------------------------------------------------
# Provider find-or-create (moved from seed.py)
# ---------------------------------------------------------------------------


async def _ensure_default_llm_provider(session: AsyncSession) -> LLMProvider:
    settings = get_settings()
    result = await session.execute(
        select(LLMProvider).where(LLMProvider.name == "Ollama (default)")
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        provider = LLMProvider(
            name="Ollama (default)",
            provider_type="ollama",
            base_url=settings.ollama_base_url or "http://localhost:11434",
            default_model=settings.ollama_default_model,
        )
        session.add(provider)
        await session.flush()
        logger.info("Created default Ollama LLM provider (%s)", provider.base_url)
    return provider


async def _ensure_cuda_llm_provider(session: AsyncSession) -> LLMProvider:
    settings = get_settings()
    result = await session.execute(
        select(LLMProvider).where(LLMProvider.name == "Ollama-CUDA (GPU)")
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        provider = LLMProvider(
            name="Ollama-CUDA (GPU)",
            provider_type="ollama",
            base_url=settings.ollama_cuda_base_url or settings.ollama_base_url,
            default_model=settings.ollama_cuda_default_model,
        )
        session.add(provider)
        await session.flush()
        logger.info("Created Ollama-CUDA LLM provider (%s)", provider.base_url)
    return provider


async def _ensure_rocm_llm_provider(session: AsyncSession) -> LLMProvider:
    settings = get_settings()
    result = await session.execute(
        select(LLMProvider).where(LLMProvider.name == "Ollama-ROCm (GPU)")
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        provider = LLMProvider(
            name="Ollama-ROCm (GPU)",
            provider_type="ollama",
            base_url=settings.ollama_rocm_base_url or settings.ollama_base_url,
            default_model=settings.ollama_rocm_default_model,
        )
        session.add(provider)
        await session.flush()
        logger.info("Created Ollama-ROCm LLM provider (%s)", provider.base_url)
    return provider


async def _ensure_speaches_stt_provider(session: AsyncSession) -> STTProvider:
    settings = get_settings()
    result = await session.execute(
        select(STTProvider).where(STTProvider.name == "Speaches")
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        provider = STTProvider(
            name="Speaches",
            provider_type="whisper_openai_compatible",
            base_url=settings.whisper_base_url or "http://speaches:8000",
            default_model=settings.whisper_model or "Systran/faster-whisper-large-v3",
        )
        session.add(provider)
        await session.flush()
        logger.info("Created Speaches STT provider (%s)", provider.base_url)
    return provider


async def _ensure_rocm_stt_provider(session: AsyncSession) -> Optional[STTProvider]:
    settings = get_settings()
    if not settings.whisper_rocm_base_url:
        return None
    result = await session.execute(
        select(STTProvider).where(STTProvider.name == "Whisper-ROCm (GPU)")
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        provider = STTProvider(
            name="Whisper-ROCm (GPU)",
            provider_type="whisper_openai_compatible",
            base_url=settings.whisper_rocm_base_url,
            default_model=settings.whisper_rocm_model,
        )
        session.add(provider)
        await session.flush()
        logger.info("Created Whisper-ROCm STT provider (%s)", provider.base_url)
    return provider


async def _ensure_n8n_tool_provider(session: AsyncSession) -> Optional[ToolProvider]:
    settings = get_settings()
    if not settings.n8n_api_key:
        return None
    result = await session.execute(
        select(ToolProvider).where(ToolProvider.name == "n8n")
    )
    provider = result.scalars().first()
    if provider is None:
        provider = ToolProvider(
            name="n8n",
            provider_type="n8n",
            base_url=settings.n8n_url,
            api_key=settings.n8n_api_key,
            is_active=True,
            health_status="unknown",
        )
        session.add(provider)
        await session.flush()
        logger.info("Created n8n tool provider (%s)", provider.base_url)
    return provider


# ---------------------------------------------------------------------------
# Provider resolution for a single workflow
# ---------------------------------------------------------------------------


async def _resolve_llm_provider(
    session: AsyncSession, backend: Optional[str],
) -> Optional[LLMProvider]:
    """Find the best LLM provider for the given backend preference."""
    settings = get_settings()
    selected = settings.selected_backends

    if backend == "cuda":
        return await _ensure_cuda_llm_provider(session)
    if backend == "rocm":
        return await _ensure_rocm_llm_provider(session)

    # No backend specified — pick best default based on configured backends
    for key in ("rocm", "cuda"):
        if key in selected:
            if key == "rocm":
                return await _ensure_rocm_llm_provider(session)
            return await _ensure_cuda_llm_provider(session)

    return await _ensure_default_llm_provider(session)


async def _resolve_stt_provider(
    session: AsyncSession, backend: Optional[str],
) -> Optional[STTProvider]:
    """Find the best STT provider for the given backend preference."""
    settings = get_settings()
    selected = settings.selected_backends

    if backend == "rocm":
        rocm = await _ensure_rocm_stt_provider(session)
        if rocm:
            return rocm
        return await _ensure_speaches_stt_provider(session)
    if backend == "cuda":
        return await _ensure_speaches_stt_provider(session)

    # No backend specified — pick best default
    for key in ("rocm", "cuda"):
        if key in selected:
            if key == "rocm":
                rocm = await _ensure_rocm_stt_provider(session)
                if rocm:
                    return rocm
            return await _ensure_speaches_stt_provider(session)

    return await _ensure_speaches_stt_provider(session)


# ---------------------------------------------------------------------------
# n8n readiness check (simple health check — no piece sync needed)
# ---------------------------------------------------------------------------


async def _check_n8n_ready() -> bool:
    """Check if n8n is reachable and ready for flow provisioning.

    Unlike Activepieces, n8n has all nodes bundled locally and is ready
    immediately after startup.  This just does a quick health check.
    """
    settings = get_settings()
    if not settings.n8n_api_key:
        return False

    from src.integrations.n8n import N8nProvider

    n8n = N8nProvider(
        base_url=settings.n8n_url,
        api_key=settings.n8n_api_key,
    )

    try:
        result = await n8n.health_check()
        if result.get("healthy"):
            logger.info("n8n is ready for provisioning")
            return True
    except Exception as e:
        logger.debug("n8n readiness check failed: %s", e)

    logger.info("n8n is not ready")
    return False


async def _provision_n8n_flow(
    session: AsyncSession, workflow: Workflow, meta: dict,
) -> bool:
    """Create an n8n webhook flow for a workflow.

    Handles cleanup of orphaned flows from previous failed attempts.
    Returns True on success, False on failure.
    """
    settings = get_settings()
    from src.integrations.n8n import N8nError, N8nProvider

    n8n = N8nProvider(
        base_url=settings.n8n_url,
        api_key=settings.n8n_api_key,
    )

    flow_name = meta.get("n8n_workflow_name", workflow.name)
    logger.info("Provisioning n8n flow '%s' for '%s'", flow_name, workflow.slug)

    # Clean up orphaned flow from a previous failed attempt
    if workflow.external_flow_id:
        logger.info(
            "Cleaning up orphaned n8n flow %s for '%s'",
            workflow.external_flow_id, workflow.slug,
        )
        deleted = await n8n.delete_flow(workflow.external_flow_id)
        if deleted:
            logger.info("Deleted orphaned n8n flow %s", workflow.external_flow_id)
        workflow.external_flow_id = None
        await session.flush()

    try:
        result = await n8n.create_webhook_flow(flow_name, webhook_path=workflow.slug)
        flow_id = result["flow_id"]
        webhook_url = result["webhook_url"]

        activated = await n8n.activate_flow(flow_id)
        if not activated:
            raise N8nError(f"Failed to activate flow {flow_id}")

        workflow.target_config = {
            **(workflow.target_config or {}),
            "url": webhook_url,
        }
        workflow.external_flow_id = flow_id
        workflow.is_active = True
        await session.flush()

        logger.info("Provisioned n8n flow for '%s': %s", workflow.slug, webhook_url)
        return True

    except Exception as e:
        logger.warning("n8n provisioning failed for '%s': %s", workflow.slug, e)
        return False


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------


def _validate_meta(meta: dict) -> Optional[str]:
    """Validate required fields in a workflow JSON. Returns error message or None."""
    for field in ("slug", "name", "workflow_type"):
        if not meta.get(field):
            return f"Missing required field: {field}"
    return None


async def import_workflow(session: AsyncSession, meta: dict) -> ImportResult:
    """Import a single workflow from a JSON definition.

    Handles:
    - Validation of required fields
    - Duplicate detection (idempotent)
    - Provider find-or-create
    - Workflow record creation with permissions
    - n8n flow provisioning (best-effort with health check)
    """
    # Validate
    error = _validate_meta(meta)
    if error:
        return ImportResult(status="error", message=error)

    slug = meta["slug"]
    name = meta["name"]
    requires = meta.get("requires", [])
    backend = meta.get("backend")

    # Check for existing workflow
    existing_result = await session.execute(
        select(Workflow).where(Workflow.slug == slug)
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        if existing.is_active:
            return ImportResult(
                status="already_exists", slug=slug, name=existing.name,
            )

        # Inactive + requires n8n → retry provisioning
        if (
            "n8n" in requires
            and existing.target_config
            and existing.target_config.get("_preset") == "n8n"
            and not existing.target_config.get("url")
        ):
            n8n_ready = await _check_n8n_ready()
            if n8n_ready:
                success = await _provision_n8n_flow(session, existing, meta)
                if success:
                    return ImportResult(
                        status="reprovisioned", slug=slug, name=existing.name,
                    )
            return ImportResult(
                status="created_inactive", slug=slug, name=existing.name,
                message="n8n not ready for provisioning",
            )

        return ImportResult(
            status="already_exists", slug=slug, name=existing.name,
        )

    # --- Resolve providers ---

    llm_provider = None
    stt_provider = None
    tool_provider = None

    if "llm" in requires:
        llm_provider = await _resolve_llm_provider(session, backend)

    if "whisper" in requires:
        stt_provider = await _resolve_stt_provider(session, backend)

    if "n8n" in requires:
        tool_provider = await _ensure_n8n_tool_provider(session)

    # --- Build recipe ---

    sources = meta.get("input_sources", ["text_selection"])

    if "audio" in sources:
        recipe = build_recipe(
            sources,
            file_config={
                "accept": meta.get("audio_accept", "audio/*"),
                "max_size_mb": meta.get("audio_max_size_mb", 50),
                "label": meta.get("audio_label", "Audio recording"),
                "required": True,
            },
        )
    else:
        recipe = build_recipe(sources)

    # --- Build target_config ---

    if "whisper" in requires:
        if stt_provider:
            target_config = build_stt_target()
        else:
            target_config = build_whisper_target()
    elif "llm" in requires:
        target_config = build_llm_target(
            prompt_template=meta.get("llm_prompt", "{{ text }}"),
            temperature=meta.get("llm_temperature", 0.3),
        )
    elif "n8n" in requires:
        form_fields = meta.get("form_fields", [])
        recipe = build_recipe(sources, form_fields if form_fields else None)
        target_config = build_n8n_target("")
    else:
        target_config = {}

    # --- Create workflow ---

    workflow = Workflow(
        slug=slug,
        name=name,
        description=meta.get("description"),
        category=meta.get("category"),
        workflow_type=meta.get("workflow_type"),
        recipe=recipe,
        target_config=target_config,
        output_action=meta.get("output_action"),
        default_hotkey=meta.get("default_hotkey"),
        input_type=meta.get("input_type", "text"),
        output_type=meta.get("output_type", "text"),
        execution_type=meta.get("execution_type", "tool"),
        llm_provider_id=llm_provider.id if llm_provider and "llm" in requires else None,
        llm_model=(
            (None if llm_provider else meta.get("llm_model"))
            if "llm" in requires
            else None
        ),
        stt_provider_id=stt_provider.id if stt_provider and "whisper" in requires else None,
        stt_model=None,
        tool_provider_id=tool_provider.id if tool_provider and "n8n" in requires else None,
    )
    session.add(workflow)
    await session.flush()

    # Default permissions
    for group in ("standard-users", "admin-users"):
        session.add(WorkflowPermission(
            workflow_id=workflow.id,
            group_name=group,
            permission_level="execute",
        ))
    await session.flush()

    # --- n8n provisioning (best-effort) ---

    if "n8n" in requires:
        n8n_ready = await _check_n8n_ready()
        if n8n_ready:
            success = await _provision_n8n_flow(session, workflow, meta)
            if not success:
                workflow.is_active = False
                await session.flush()
                return ImportResult(
                    status="created_inactive", slug=slug, name=name,
                    message="Workflow created but n8n flow provisioning failed",
                )
        else:
            workflow.is_active = False
            await session.flush()
            return ImportResult(
                status="created_inactive", slug=slug, name=name,
                message="Workflow created but n8n not ready",
            )

    logger.info("Imported workflow '%s' (%s)", slug, name)
    return ImportResult(status="created", slug=slug, name=name)
