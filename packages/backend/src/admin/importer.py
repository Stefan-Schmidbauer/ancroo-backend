"""Import entities from JSON definitions.

Accepts JSON with a `_type` discriminator and writes it 1:1 to the database.
No auto-magic, no environment sniffing, no n8n provisioning.
If a referenced dependency does not exist, the import fails with a clear message.

Used by:
- Admin UI file upload (POST /admin/import)
- API endpoint (POST /admin/api/import)
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    Category,
    LLMModel,
    STTModel,
    Tool,
    Workflow,
    WorkflowPermission,
)

logger = logging.getLogger(__name__)

# Import order for bundle items (dependencies first)
_TYPE_ORDER = {
    "category": 0,
    "llm_model": 1,
    "stt_model": 2,
    "tool": 3,
    "workflow": 4,
}


@dataclass
class ImportResult:
    status: str  # "created", "skipped", "error"
    entity_type: str = ""
    name: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        d = {"status": self.status, "entity_type": self.entity_type}
        if self.name:
            d["name"] = self.name
        if self.message:
            d["message"] = self.message
        return d


@dataclass
class BundleResult:
    results: list[ImportResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"results": [r.to_dict() for r in self.results]}


async def import_item(session: AsyncSession, data: dict) -> ImportResult | BundleResult:
    """Route to the correct importer based on _type."""
    item_type = data.get("_type")
    if item_type == "llm_model":
        return await _import_llm_model(session, data)
    if item_type == "stt_model":
        return await _import_stt_model(session, data)
    if item_type == "tool":
        return await _import_tool(session, data)
    if item_type == "category":
        return await _import_category(session, data)
    if item_type == "workflow":
        return await _import_workflow(session, data)
    if item_type == "bundle":
        return await _import_bundle(session, data)
    return ImportResult(
        status="error",
        entity_type=str(item_type or "unknown"),
        message=f"Unknown type: '{item_type}'. Expected: llm_model, stt_model, tool, category, workflow, or bundle.",
    )


# ---------------------------------------------------------------------------
# LLM Model
# ---------------------------------------------------------------------------


async def _import_llm_model(session: AsyncSession, data: dict) -> ImportResult:
    name = data.get("name")
    if not name:
        return ImportResult(status="error", entity_type="llm_model", message="Missing required field: name")

    existing = await session.execute(select(LLMModel).where(LLMModel.name == name))
    if existing.scalar_one_or_none():
        return ImportResult(status="skipped", entity_type="llm_model", name=name, message="Already exists")

    model = LLMModel(
        name=name,
        provider_type=data.get("provider_type", "ollama"),
        base_url=data.get("base_url", ""),
        endpoint_execute=data.get("endpoint_execute", "/v1/chat/completions"),
        endpoint_models=data.get("endpoint_models", "/v1/models"),
        model_id=data.get("model_id", ""),
        default_temperature=data.get("default_temperature", 0.3),
        config=data.get("config", {}),
        is_active=data.get("is_active", True),
    )
    session.add(model)
    await session.flush()
    logger.info("Imported LLM model '%s'", name)
    return ImportResult(status="created", entity_type="llm_model", name=name)


# ---------------------------------------------------------------------------
# STT Model
# ---------------------------------------------------------------------------


async def _import_stt_model(session: AsyncSession, data: dict) -> ImportResult:
    name = data.get("name")
    if not name:
        return ImportResult(status="error", entity_type="stt_model", message="Missing required field: name")

    existing = await session.execute(select(STTModel).where(STTModel.name == name))
    if existing.scalar_one_or_none():
        return ImportResult(status="skipped", entity_type="stt_model", name=name, message="Already exists")

    model = STTModel(
        name=name,
        provider_type=data.get("provider_type", "whisper_openai_compatible"),
        base_url=data.get("base_url", ""),
        model_id=data.get("model_id", ""),
        default_language=data.get("default_language"),
        config=data.get("config", {}),
        is_active=data.get("is_active", True),
        is_default=data.get("is_default", False),
    )
    session.add(model)
    await session.flush()
    logger.info("Imported STT model '%s'", name)
    return ImportResult(status="created", entity_type="stt_model", name=name)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


async def _import_tool(session: AsyncSession, data: dict) -> ImportResult:
    name = data.get("name")
    if not name:
        return ImportResult(status="error", entity_type="tool", message="Missing required field: name")

    existing = await session.execute(select(Tool).where(Tool.name == name))
    if existing.scalar_one_or_none():
        return ImportResult(status="skipped", entity_type="tool", name=name, message="Already exists")

    tool = Tool(
        name=name,
        tool_type=data.get("tool_type", "custom_api"),
        endpoint_url=data.get("endpoint_url", ""),
        http_method=data.get("http_method", "POST"),
        headers=data.get("headers", {}),
        payload_template=data.get("payload_template"),
        response_mapping=data.get("response_mapping"),
        timeout=data.get("timeout", 120),
        description=data.get("description"),
        input_schema=data.get("input_schema"),
        output_schema=data.get("output_schema"),
        is_active=data.get("is_active", True),
        source=data.get("source", "imported"),
        source_id=data.get("source_id"),
        n8n_base_url=data.get("n8n_base_url"),
        n8n_flow_id=data.get("n8n_flow_id"),
    )
    session.add(tool)
    await session.flush()
    logger.info("Imported tool '%s'", name)
    return ImportResult(status="created", entity_type="tool", name=name)


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------


async def _import_category(session: AsyncSession, data: dict) -> ImportResult:
    name = data.get("name")
    if not name:
        return ImportResult(status="error", entity_type="category", message="Missing required field: name")

    existing = await session.execute(
        select(Category).where(sa_func.lower(Category.name) == name.lower())
    )
    if existing.scalar_one_or_none():
        return ImportResult(status="skipped", entity_type="category", name=name, message="Already exists")

    category = Category(
        name=name,
        icon=data.get("icon", "\U0001f527"),
    )
    session.add(category)
    await session.flush()
    logger.info("Imported category '%s'", name)
    return ImportResult(status="created", entity_type="category", name=name)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


async def _import_workflow(session: AsyncSession, data: dict) -> ImportResult:
    slug = data.get("slug")
    name = data.get("name")
    wf_type = data.get("workflow_type")

    for field_name, value in [("slug", slug), ("name", name), ("workflow_type", wf_type)]:
        if not value:
            return ImportResult(
                status="error", entity_type="workflow",
                message=f"Missing required field: {field_name}",
            )

    # Check existing
    existing = await session.execute(select(Workflow).where(Workflow.slug == slug))
    if existing.scalar_one_or_none():
        return ImportResult(status="skipped", entity_type="workflow", name=name, message=f"Workflow '{slug}' already exists")

    # Resolve LLM model by name
    llm_model_id = None
    llm_model_name = data.get("llm_model_name")
    if llm_model_name:
        result = await session.execute(select(LLMModel).where(LLMModel.name == llm_model_name))
        llm_model = result.scalar_one_or_none()
        if not llm_model:
            return ImportResult(
                status="error", entity_type="workflow", name=name,
                message=f"LLM Model '{llm_model_name}' not found. Import it first or create it manually.",
            )
        llm_model_id = llm_model.id

    # Resolve STT model by name
    stt_model_id = None
    stt_model_name = data.get("stt_model_name")
    if stt_model_name:
        result = await session.execute(select(STTModel).where(STTModel.name == stt_model_name))
        stt_model = result.scalar_one_or_none()
        if not stt_model:
            return ImportResult(
                status="error", entity_type="workflow", name=name,
                message=f"STT Model '{stt_model_name}' not found. Import it first or create it manually.",
            )
        stt_model_id = stt_model.id

    # Resolve tool by name
    tool_id = None
    tool_name = data.get("tool_name")
    if tool_name:
        result = await session.execute(select(Tool).where(Tool.name == tool_name))
        tool = result.scalar_one_or_none()
        if not tool:
            return ImportResult(
                status="error", entity_type="workflow", name=name,
                message=f"Tool '{tool_name}' not found. Import it first or create it manually.",
            )
        tool_id = tool.id

    # Resolve category by name
    category_id = None
    category_name = data.get("category_name")
    if category_name:
        result = await session.execute(
            select(Category).where(sa_func.lower(Category.name) == category_name.lower())
        )
        category = result.scalar_one_or_none()
        if not category:
            return ImportResult(
                status="error", entity_type="workflow", name=name,
                message=f"Category '{category_name}' not found. Import it first or create it manually.",
            )
        category_id = category.id

    # Create workflow
    workflow = Workflow(
        slug=slug,
        name=name,
        description=data.get("description"),
        workflow_type=wf_type,
        category_id=category_id,
        llm_model_id=llm_model_id,
        stt_model_id=stt_model_id,
        tool_id=tool_id,
        prompt_template=data.get("prompt_template"),
        temperature=data.get("temperature"),
        recipe=data.get("recipe"),
        output_action=data.get("output_action"),
        default_hotkey=data.get("default_hotkey"),
        demo_url=data.get("demo_url"),
        timeout_seconds=data.get("timeout_seconds", 60),
        version=data.get("version", "1.0.0"),
        is_active=data.get("is_active", True),
    )
    session.add(workflow)
    await session.flush()

    # Create permissions
    permissions = data.get("permissions", [])
    if not permissions:
        # Default permissions if none specified
        permissions = [
            {"group_name": "standard-users", "permission_level": "execute"},
            {"group_name": "admin-users", "permission_level": "execute"},
        ]
    for perm in permissions:
        if perm.get("group_name"):
            session.add(WorkflowPermission(
                workflow_id=workflow.id,
                group_name=perm["group_name"],
                permission_level=perm.get("permission_level", "execute"),
            ))
    await session.flush()

    logger.info("Imported workflow '%s' (%s)", slug, name)
    return ImportResult(status="created", entity_type="workflow", name=name)


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


async def _import_bundle(session: AsyncSession, data: dict) -> BundleResult:
    """Import a bundle of items in dependency order."""
    items = data.get("items", [])
    if not items:
        return BundleResult(results=[
            ImportResult(status="error", entity_type="bundle", message="Bundle contains no items"),
        ])

    # Sort by dependency order
    sorted_items = sorted(items, key=lambda x: _TYPE_ORDER.get(x.get("_type", ""), 99))

    results = []
    for item in sorted_items:
        result = await import_item(session, item)
        if isinstance(result, BundleResult):
            results.extend(result.results)
        else:
            results.append(result)

    return BundleResult(results=results)
