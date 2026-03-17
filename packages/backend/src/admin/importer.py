"""Workflow import from JSON definitions.

Accepts a workflow JSON (the metadata.json format) and creates the
corresponding database records: LLM models, STT models, tools (find-or-create),
workflow, and permissions.  For workflows that require n8n, webhook flow
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
    Category,
    LLMModel,
    STTModel,
    Tool,
    Workflow,
    WorkflowPermission,
)

logger = logging.getLogger(__name__)

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
# LLM Model find-or-create
# ---------------------------------------------------------------------------


async def _ensure_default_llm_model(session: AsyncSession) -> LLMModel:
    settings = get_settings()
    result = await session.execute(
        select(LLMModel).where(LLMModel.name == "Ollama (default)")
    )
    model = result.scalar_one_or_none()
    if model is None:
        model = LLMModel(
            name="Ollama (default)",
            provider_type="ollama",
            base_url=settings.ollama_base_url or "http://localhost:11434",
            model_id=settings.ollama_default_model,
        )
        session.add(model)
        await session.flush()
        logger.info("Created default Ollama LLM model (%s)", model.base_url)
    return model


async def _ensure_cuda_llm_model(session: AsyncSession) -> LLMModel:
    settings = get_settings()
    result = await session.execute(
        select(LLMModel).where(LLMModel.name == "Ollama-CUDA (GPU)")
    )
    model = result.scalar_one_or_none()
    if model is None:
        model = LLMModel(
            name="Ollama-CUDA (GPU)",
            provider_type="ollama",
            base_url=settings.ollama_cuda_base_url or settings.ollama_base_url,
            model_id=settings.ollama_cuda_default_model,
        )
        session.add(model)
        await session.flush()
        logger.info("Created Ollama-CUDA LLM model (%s)", model.base_url)
    return model


async def _ensure_rocm_llm_model(session: AsyncSession) -> LLMModel:
    settings = get_settings()
    result = await session.execute(
        select(LLMModel).where(LLMModel.name == "Ollama-ROCm (GPU)")
    )
    model = result.scalar_one_or_none()
    if model is None:
        model = LLMModel(
            name="Ollama-ROCm (GPU)",
            provider_type="ollama",
            base_url=settings.ollama_rocm_base_url or settings.ollama_base_url,
            model_id=settings.ollama_rocm_default_model,
        )
        session.add(model)
        await session.flush()
        logger.info("Created Ollama-ROCm LLM model (%s)", model.base_url)
    return model


# ---------------------------------------------------------------------------
# STT Model find-or-create
# ---------------------------------------------------------------------------


async def _ensure_speaches_stt_model(session: AsyncSession) -> STTModel:
    settings = get_settings()
    result = await session.execute(
        select(STTModel).where(STTModel.name == "Speaches")
    )
    model = result.scalar_one_or_none()
    if model is None:
        model = STTModel(
            name="Speaches",
            provider_type="whisper_openai_compatible",
            base_url=settings.whisper_base_url or "http://speaches:8000",
            model_id=settings.whisper_model or "Systran/faster-whisper-large-v3",
        )
        session.add(model)
        await session.flush()
        logger.info("Created Speaches STT model (%s)", model.base_url)
    return model


async def _ensure_rocm_stt_model(session: AsyncSession) -> Optional[STTModel]:
    settings = get_settings()
    if not settings.whisper_rocm_base_url:
        return None
    result = await session.execute(
        select(STTModel).where(STTModel.name == "Whisper-ROCm (GPU)")
    )
    model = result.scalar_one_or_none()
    if model is None:
        model = STTModel(
            name="Whisper-ROCm (GPU)",
            provider_type="whisper_openai_compatible",
            base_url=settings.whisper_rocm_base_url,
            model_id=settings.whisper_rocm_model,
        )
        session.add(model)
        await session.flush()
        logger.info("Created Whisper-ROCm STT model (%s)", model.base_url)
    return model


# ---------------------------------------------------------------------------
# Tool find-or-create (n8n webhooks, AR plugins, custom APIs)
# ---------------------------------------------------------------------------


async def _ensure_n8n_tool(
    session: AsyncSession, slug: str, flow_name: str,
) -> Optional[Tool]:
    """Create a Tool entry for an n8n webhook (provisioned later)."""
    settings = get_settings()
    if not settings.n8n_api_key:
        return None

    # Check if tool already exists for this workflow
    source_id = f"n8n:{slug}"
    result = await session.execute(
        select(Tool).where(Tool.source_id == source_id)
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        tool = Tool(
            name=flow_name,
            tool_type="n8n_webhook",
            endpoint_url="",  # Filled during n8n provisioning
            http_method="POST",
            headers={"Content-Type": "application/json"},
            payload_template="{{ _input | tojson }}",
            response_mapping="$.result",
            timeout=120,
            source="imported",
            source_id=source_id,
            n8n_base_url=settings.n8n_url,
            n8n_api_key=settings.n8n_api_key,
        )
        session.add(tool)
        await session.flush()
        logger.info("Created n8n tool '%s'", flow_name)
    return tool


async def _ensure_custom_tool(
    session: AsyncSession, slug: str, target_config: dict,
) -> Tool:
    """Create a Tool entry from a custom target_config (e.g. AR plugin endpoints)."""
    source_id = f"custom:{slug}"
    result = await session.execute(
        select(Tool).where(Tool.source_id == source_id)
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        tool = Tool(
            name=slug,
            tool_type="custom_api",
            endpoint_url=target_config.get("url", ""),
            http_method=target_config.get("method", "POST"),
            headers=target_config.get("headers", {"Content-Type": "application/json"}),
            payload_template=target_config.get("payload_template"),
            response_mapping=target_config.get("response_mapping", "$.result"),
            timeout=target_config.get("timeout", 120),
            source="imported",
            source_id=source_id,
        )
        session.add(tool)
        await session.flush()
        logger.info("Created custom tool '%s'", slug)
    return tool


# ---------------------------------------------------------------------------
# Resolution (pick best model for the backend)
# ---------------------------------------------------------------------------


async def _resolve_llm_model(
    session: AsyncSession, backend: Optional[str],
) -> Optional[LLMModel]:
    settings = get_settings()
    selected = settings.selected_backends

    if backend == "cuda":
        return await _ensure_cuda_llm_model(session)
    if backend == "rocm":
        return await _ensure_rocm_llm_model(session)

    for key in ("rocm", "cuda"):
        if key in selected:
            if key == "rocm":
                return await _ensure_rocm_llm_model(session)
            return await _ensure_cuda_llm_model(session)

    return await _ensure_default_llm_model(session)


async def _resolve_stt_model(
    session: AsyncSession, backend: Optional[str],
) -> Optional[STTModel]:
    settings = get_settings()
    selected = settings.selected_backends

    if backend == "rocm":
        rocm = await _ensure_rocm_stt_model(session)
        if rocm:
            return rocm
        return await _ensure_speaches_stt_model(session)
    if backend == "cuda":
        return await _ensure_speaches_stt_model(session)

    for key in ("rocm", "cuda"):
        if key in selected:
            if key == "rocm":
                rocm = await _ensure_rocm_stt_model(session)
                if rocm:
                    return rocm
            return await _ensure_speaches_stt_model(session)

    return await _ensure_speaches_stt_model(session)


# ---------------------------------------------------------------------------
# n8n provisioning
# ---------------------------------------------------------------------------


async def _check_n8n_ready() -> bool:
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
    session: AsyncSession, workflow: Workflow, tool: Tool, meta: dict,
) -> bool:
    """Link to an existing n8n webhook flow or create one, then update the tool."""
    settings = get_settings()
    from src.integrations.n8n import N8nError, N8nProvider

    n8n = N8nProvider(
        base_url=settings.n8n_url,
        api_key=settings.n8n_api_key,
    )

    flow_name = meta.get("n8n_workflow_name", workflow.name)
    logger.info("Provisioning n8n flow '%s' for '%s'", flow_name, workflow.slug)

    try:
        # First: check if a matching flow already exists in n8n
        existing_flow = await n8n.find_flow_by_name(flow_name)
        if existing_flow and existing_flow.get("webhook_url"):
            flow_id = existing_flow["id"]
            webhook_url = existing_flow["webhook_url"]

            if not existing_flow.get("active"):
                await n8n.activate_flow(flow_id)

            tool.endpoint_url = webhook_url
            tool.n8n_flow_id = flow_id
            workflow.is_active = True
            await session.flush()

            logger.info("Linked existing n8n flow for '%s': %s", workflow.slug, webhook_url)
            return True

        # Clean up orphaned flow from a previous failed attempt
        if tool.n8n_flow_id:
            logger.info("Cleaning up orphaned n8n flow %s", tool.n8n_flow_id)
            deleted = await n8n.delete_flow(tool.n8n_flow_id)
            if deleted:
                logger.info("Deleted orphaned n8n flow %s", tool.n8n_flow_id)
            tool.n8n_flow_id = None
            await session.flush()

        # Create new flow
        custom_wf = meta.get("n8n_workflow_json")
        result = await n8n.create_webhook_flow(
            flow_name,
            webhook_path=workflow.slug,
            custom_workflow_json=custom_wf,
        )
        flow_id = result["flow_id"]
        webhook_url = result["webhook_url"]

        activated = await n8n.activate_flow(flow_id)
        if not activated:
            raise N8nError(f"Failed to activate flow {flow_id}")

        # Update the tool with the webhook URL
        tool.endpoint_url = webhook_url
        tool.n8n_flow_id = flow_id
        workflow.is_active = True
        await session.flush()

        logger.info("Provisioned n8n flow for '%s': %s", workflow.slug, webhook_url)
        return True

    except Exception as e:
        logger.warning("n8n provisioning failed for '%s': %s", workflow.slug, e)
        return False


# ---------------------------------------------------------------------------
# Category find-or-create
# ---------------------------------------------------------------------------

_CATEGORY_ICONS = {
    "text": "\u270F\uFE0F",
    "voice": "\uD83C\uDF99\uFE0F",
    "automation": "\u26A1",
    "translation": "\uD83C\uDF10",
    "code": "\uD83D\uDCBB",
}


async def _resolve_category(
    session: AsyncSession, name: Optional[str],
) -> Optional[Category]:
    """Find or create a category by name. Returns None if name is empty."""
    if not name:
        return None
    from sqlalchemy import func as sa_func
    result = await session.execute(
        select(Category).where(sa_func.lower(Category.name) == name.lower())
    )
    category = result.scalar_one_or_none()
    if category is None:
        icon = _CATEGORY_ICONS.get(name, "\U0001f527")
        category = Category(name=name, icon=icon)
        session.add(category)
        await session.flush()
        logger.info("Created category '%s' (%s)", name, icon)
    return category


# ---------------------------------------------------------------------------
# Recipe builder
# ---------------------------------------------------------------------------


def _build_recipe(meta: dict) -> dict:
    """Build a collection recipe from workflow metadata."""
    if meta.get("recipe"):
        return meta["recipe"]

    sources = meta.get("input_sources", ["text_selection"])
    recipe: dict = {"collect": sources}

    form_fields = meta.get("form_fields")
    if form_fields and "form_fields" in sources:
        recipe["form_fields"] = form_fields

    output_fields = meta.get("output_fields")
    if output_fields:
        recipe["output_fields"] = output_fields

    if "audio" in sources:
        recipe["file_config"] = {
            "accept": meta.get("audio_accept", "audio/*"),
            "max_size_mb": meta.get("audio_max_size_mb", 50),
            "label": meta.get("audio_label", "Audio recording"),
            "required": True,
        }

    return recipe


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------


def _validate_meta(meta: dict) -> Optional[str]:
    for field in ("slug", "name", "workflow_type"):
        if not meta.get(field):
            return f"Missing required field: {field}"
    return None


async def import_workflow(session: AsyncSession, meta: dict) -> ImportResult:
    """Import a single workflow from a JSON definition."""
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
        if "n8n" in requires and existing.tool_id:
            tool = await session.get(Tool, existing.tool_id)
            if tool and not tool.endpoint_url:
                n8n_ready = await _check_n8n_ready()
                if n8n_ready:
                    success = await _provision_n8n_flow(session, existing, tool, meta)
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

    # --- Resolve execution target ---

    llm_model = None
    stt_model = None
    tool = None

    if "llm" in requires:
        llm_model = await _resolve_llm_model(session, backend)

    if "whisper" in requires:
        stt_model = await _resolve_stt_model(session, backend)

    if "n8n" in requires:
        flow_name = meta.get("n8n_workflow_name", name)
        tool = await _ensure_n8n_tool(session, slug, flow_name)

    if meta.get("target_config") and not tool:
        # Custom workflows with direct target_config (e.g. AR plugin endpoints)
        tool = await _ensure_custom_tool(session, slug, meta["target_config"])

    if meta.get("tool") and not tool:
        # Tool block format (AR plugins, custom APIs) — map to target_config
        tool_meta = meta["tool"]
        target_config = {
            "url": tool_meta.get("endpoint_url", ""),
            "method": tool_meta.get("http_method", "POST"),
            "headers": tool_meta.get("headers", {"Content-Type": "application/json"}),
            "payload_template": tool_meta.get("payload_template"),
            "response_mapping": tool_meta.get("response_mapping", "$.result"),
            "timeout": tool_meta.get("timeout", 120),
        }
        tool = await _ensure_custom_tool(session, slug, target_config)

    # --- Resolve category ---

    category = await _resolve_category(session, meta.get("category"))

    # --- Build recipe ---

    recipe = _build_recipe(meta)

    # --- Create workflow ---

    workflow = Workflow(
        slug=slug,
        name=name,
        description=meta.get("description"),
        category_id=category.id if category else None,
        workflow_type=meta.get("workflow_type"),
        recipe=recipe,
        output_action=meta.get("output_action"),
        default_hotkey=meta.get("default_hotkey"),
        demo_url=meta.get("demo_url"),
        timeout_seconds=meta.get("timeout_seconds", 60),
        # Execution target (exactly one)
        llm_model_id=llm_model.id if llm_model else None,
        prompt_template=meta.get("llm_prompt") if llm_model else None,
        temperature=meta.get("llm_temperature") if llm_model else None,
        stt_model_id=stt_model.id if stt_model else None,
        tool_id=tool.id if tool else None,
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

    if "n8n" in requires and tool:
        n8n_ready = await _check_n8n_ready()
        if n8n_ready:
            success = await _provision_n8n_flow(session, workflow, tool, meta)
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
