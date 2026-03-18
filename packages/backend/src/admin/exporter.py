"""Export database entities to portable JSON.

Each entity is serialized with a `_type` discriminator and `_version` field.
Secrets (api_key, n8n_api_key) are excluded from export — the admin sets
these manually after import on the target instance.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Category, LLMModel, STTModel, Tool, Workflow


def export_llm_model(model: LLMModel) -> dict:
    return {
        "_type": "llm_model",
        "_version": 1,
        "name": model.name,
        "provider_type": model.provider_type,
        "base_url": model.base_url,
        "endpoint_execute": model.endpoint_execute,
        "endpoint_models": model.endpoint_models,
        "model_id": model.model_id,
        "default_temperature": model.default_temperature,
        "config": model.config or {},
        "is_active": model.is_active,
    }


def export_stt_model(model: STTModel) -> dict:
    return {
        "_type": "stt_model",
        "_version": 1,
        "name": model.name,
        "provider_type": model.provider_type,
        "base_url": model.base_url,
        "model_id": model.model_id,
        "default_language": model.default_language,
        "config": model.config or {},
        "is_active": model.is_active,
        "is_default": model.is_default,
    }


def export_tool(tool: Tool) -> dict:
    return {
        "_type": "tool",
        "_version": 1,
        "name": tool.name,
        "tool_type": tool.tool_type,
        "endpoint_url": tool.endpoint_url,
        "http_method": tool.http_method,
        "headers": tool.headers or {},
        "payload_template": tool.payload_template,
        "response_mapping": tool.response_mapping,
        "timeout": tool.timeout,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "is_active": tool.is_active,
        "source": tool.source,
        "source_id": tool.source_id,
        "n8n_base_url": tool.n8n_base_url,
        "n8n_flow_id": tool.n8n_flow_id,
    }


def export_category(category: Category) -> dict:
    return {
        "_type": "category",
        "_version": 1,
        "name": category.name,
        "icon": category.icon,
    }


def export_workflow(workflow: Workflow) -> dict:
    permissions = []
    for perm in workflow.permissions:
        entry: dict = {"permission_level": perm.permission_level}
        if perm.group_name:
            entry["group_name"] = perm.group_name
        permissions.append(entry)

    return {
        "_type": "workflow",
        "_version": 1,
        "slug": workflow.slug,
        "name": workflow.name,
        "description": workflow.description,
        "workflow_type": workflow.workflow_type,
        "category_name": workflow.category_rel.name if workflow.category_rel else None,
        "llm_model_name": workflow.llm_model.name if workflow.llm_model else None,
        "stt_model_name": workflow.stt_model.name if workflow.stt_model else None,
        "tool_name": workflow.tool.name if workflow.tool else None,
        "prompt_template": workflow.prompt_template,
        "temperature": workflow.temperature,
        "recipe": workflow.recipe,
        "output_action": workflow.output_action,
        "default_hotkey": workflow.default_hotkey,
        "demo_url": workflow.demo_url,
        "timeout_seconds": workflow.timeout_seconds,
        "version": workflow.version,
        "is_active": workflow.is_active,
        "permissions": permissions,
    }


async def export_all(session: AsyncSession) -> dict:
    """Export all entities as a bundle in dependency order."""
    categories = (await session.execute(select(Category))).scalars().all()
    llm_models = (await session.execute(select(LLMModel))).scalars().all()
    stt_models = (await session.execute(select(STTModel))).scalars().all()
    tools = (await session.execute(select(Tool))).scalars().all()
    workflows = (
        await session.execute(
            select(Workflow).options(
                selectinload(Workflow.category_rel),
                selectinload(Workflow.llm_model),
                selectinload(Workflow.stt_model),
                selectinload(Workflow.tool),
                selectinload(Workflow.permissions),
            )
        )
    ).scalars().all()

    items: list[dict] = []
    for c in categories:
        items.append(export_category(c))
    for m in llm_models:
        items.append(export_llm_model(m))
    for m in stt_models:
        items.append(export_stt_model(m))
    for t in tools:
        items.append(export_tool(t))
    for w in workflows:
        items.append(export_workflow(w))

    return {
        "_type": "bundle",
        "_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
