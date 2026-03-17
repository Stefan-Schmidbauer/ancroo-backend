"""Ancroo Runner auto-discovery client.

Queries the ancroo-runner /plugins endpoint to discover available
plugins and creates/updates Tool entries in the database.
"""

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Tool

logger = logging.getLogger(__name__)


class RunnerDiscoveryError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def discover_plugins(runner_base_url: str) -> list[dict[str, Any]]:
    """Query ancroo-runner GET /plugins and return plugin metadata."""
    url = f"{runner_base_url.rstrip('/')}/plugins"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise RunnerDiscoveryError(f"Cannot reach ancroo-runner at {url}: {e}")

    data = response.json()
    return data.get("plugins", [])


async def check_runner_health(runner_base_url: str) -> dict[str, Any]:
    """Health check for ancroo-runner."""
    url = f"{runner_base_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            return {"healthy": True, "plugins_loaded": data.get("plugins_loaded", 0)}
    except httpx.HTTPError as e:
        return {"healthy": False, "error": str(e)}


async def sync_tools_from_runner(
    db: AsyncSession,
    runner_base_url: str,
) -> dict[str, Any]:
    """Create/update Tool entries from discovered AR plugins.

    Returns sync report: {created, updated, unchanged, total, errors}.
    """
    plugins = await discover_plugins(runner_base_url)
    base_url = runner_base_url.rstrip("/")

    created = 0
    updated = 0
    unchanged = 0
    errors: list[str] = []

    for plugin in plugins:
        plugin_name = plugin.get("name", "unknown")
        description = plugin.get("description", "")
        endpoints = plugin.get("endpoints", [])

        for ep in endpoints:
            ep_path = ep.get("path", "")
            ep_desc = ep.get("description", "")

            if not ep_path:
                continue

            endpoint_url = f"{base_url}{ep_path}"
            source_id = f"{plugin_name}:{ep_path}"

            try:
                # Check if tool already exists
                stmt = select(Tool).where(
                    Tool.source == "auto_discovered",
                    Tool.source_id == source_id,
                )
                result = await db.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # Update endpoint URL if runner URL changed
                    if existing.endpoint_url != endpoint_url:
                        existing.endpoint_url = endpoint_url
                        existing.description = ep_desc or description
                        updated += 1
                    else:
                        unchanged += 1
                else:
                    # Create new tool
                    tool = Tool(
                        name=ep_desc or f"{plugin_name}: {ep_path}",
                        tool_type="ar_plugin",
                        endpoint_url=endpoint_url,
                        http_method="POST",
                        headers={"Content-Type": "application/json"},
                        response_mapping="$.result",
                        timeout=120,
                        description=description,
                        source="auto_discovered",
                        source_id=source_id,
                        is_active=True,
                    )
                    db.add(tool)
                    created += 1

            except Exception as e:
                msg = f"Error syncing {source_id}: {e}"
                logger.error(msg)
                errors.append(msg)

    await db.flush()

    total = created + updated + unchanged
    logger.info(
        "AR plugin sync: %d created, %d updated, %d unchanged, %d errors",
        created, updated, unchanged, len(errors),
    )

    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "total": total,
        "errors": errors,
    }
