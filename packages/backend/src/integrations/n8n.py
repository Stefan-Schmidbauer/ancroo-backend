"""n8n workflow automation provider.

Implements the ToolProvider protocol for n8n:
- Static API key authentication
- Clean REST API for workflow CRUD
- Deterministic webhook URLs (http://n8n:5678/webhook/<path>)
"""

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class N8nError(Exception):
    """Error from n8n API operations."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class N8nProvider:
    """n8n ToolProvider implementation.

    Args:
        base_url: n8n instance URL (e.g. ``http://n8n:5678``).
        api_key: Static API key (``X-N8N-API-KEY`` header).
        config: Optional extra config dict (unused, for protocol compat).
    """

    provider_type: str = "n8n"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        config: dict | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.config = config or {}

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """Return auth headers for n8n API requests."""
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-N8N-API-KEY"] = self._api_key
        return h

    # ------------------------------------------------------------------
    # ToolProvider protocol
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Check if n8n is reachable via /healthz."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/healthz")
                if resp.status_code == 200:
                    return {"healthy": True, "message": "n8n is healthy"}
                return {
                    "healthy": False,
                    "message": f"n8n returned HTTP {resp.status_code}",
                }
        except httpx.HTTPError as exc:
            return {"healthy": False, "message": f"n8n unreachable: {exc}"}

    async def discover_flows(self) -> list[dict[str, Any]]:
        """List all n8n workflows that have a Webhook trigger node."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/workflows",
                headers=self._headers(),
            )
            if resp.status_code == 401:
                raise N8nError("n8n API key invalid or missing", status_code=401)
            resp.raise_for_status()

        data = resp.json()
        workflows = data.get("data", data) if isinstance(data, dict) else data

        flows: list[dict[str, Any]] = []
        for wf in workflows:
            nodes = wf.get("nodes", [])
            webhook_node = _find_webhook_node(nodes)
            if webhook_node is None:
                continue

            webhook_path = webhook_node.get("parameters", {}).get("path", "")
            wf_id = str(wf.get("id", ""))
            # n8n v2 webhook URLs: /webhook/{workflowId}/webhook/{path}
            webhook_url = (
                f"{self.base_url}/webhook/{wf_id}/webhook/{webhook_path}"
                if webhook_path else ""
            )

            flows.append({
                "id": str(wf.get("id", "")),
                "name": wf.get("name", ""),
                "description": wf.get("tags", []),
                "active": wf.get("active", False),
                "has_webhook": True,
                "webhook_url": webhook_url,
                "trigger_type": "webhook",
            })

        return flows

    async def find_flow_by_name(self, display_name: str) -> dict[str, Any] | None:
        """Find a workflow by display name."""
        flows = await self.discover_flows()
        for flow in flows:
            if flow["name"] == display_name:
                return flow
        return None

    async def create_webhook_flow(
        self,
        display_name: str,
        webhook_path: str | None = None,
        custom_workflow_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an n8n webhook flow.

        If *custom_workflow_json* is provided (e.g. from an ``n8n-workflow.json``
        file), it is used as-is (with name and webhook path normalised).
        Otherwise a minimal echo flow is created as fallback.

        Args:
            display_name: Human-readable workflow name.
            webhook_path: URL path for the webhook.  Defaults to a
                slugified version of *display_name*.
            custom_workflow_json: Full n8n workflow definition (nodes,
                connections, settings).  When provided the flow is created
                from this template instead of the default echo template.

        Returns:
            ``{"flow_id": "...", "webhook_url": "..."}``
        """
        if not webhook_path:
            webhook_path = _slugify(display_name)

        if custom_workflow_json:
            # Use provided workflow definition, normalise name
            workflow_json = dict(custom_workflow_json)
            workflow_json["name"] = display_name
            # Remove read-only fields that n8n rejects on create
            workflow_json.pop("tags", None)
            workflow_json.pop("id", None)
            # Ensure webhook path matches the slug and strip local IDs
            for node in workflow_json.get("nodes", []):
                node.pop("webhookId", None)
                node.pop("id", None)
                node_type = node.get("type", "")
                if "webhook" in node_type.lower() and "respond" not in node_type.lower():
                    node.setdefault("parameters", {})["path"] = webhook_path
        else:
            # Default echo flow
            workflow_json = {
                "name": display_name,
                "nodes": [
                    {
                        "parameters": {
                            "httpMethod": "POST",
                            "path": webhook_path,
                            "responseMode": "responseNode",
                            "options": {},
                        },
                        "type": "n8n-nodes-base.webhook",
                        "typeVersion": 2,
                        "name": "Webhook",
                        "position": [250, 300],
                    },
                    {
                        "parameters": {
                            "respondWith": "json",
                            "responseBody": '={{ JSON.stringify({ result: { text: JSON.stringify($input.first().json) } }) }}',
                        },
                        "type": "n8n-nodes-base.respondToWebhook",
                        "typeVersion": 1,
                        "name": "Respond to Webhook",
                        "position": [450, 300],
                    },
                ],
                "connections": {
                    "Webhook": {
                        "main": [
                            [{"node": "Respond to Webhook", "type": "main", "index": 0}]
                        ]
                    }
                },
                "settings": {"executionOrder": "v1"},
            }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/workflows",
                headers=self._headers(),
                json=workflow_json,
            )
            if resp.status_code == 401:
                raise N8nError("n8n API key invalid or missing", status_code=401)
            if not resp.is_success:
                raise N8nError(
                    f"Failed to create workflow: HTTP {resp.status_code} — {resp.text[:200]}",
                    status_code=resp.status_code,
                )

        result = resp.json()
        flow_id = str(result.get("id", ""))
        # n8n v2 webhook URLs include the workflow ID:
        # /webhook/{workflowId}/webhook/{path}
        webhook_url = f"{self.base_url}/webhook/{flow_id}/webhook/{webhook_path}"

        logger.info("Created n8n workflow '%s' (id=%s, path=%s)", display_name, flow_id, webhook_path)
        return {"flow_id": flow_id, "webhook_url": webhook_url}

    async def activate_flow(self, flow_id: str) -> bool:
        """Activate (enable) a workflow so its webhook becomes live."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/workflows/{flow_id}/activate",
                headers=self._headers(),
            )
            if resp.is_success:
                logger.info("Activated n8n workflow %s", flow_id)
                return True
            logger.warning(
                "Failed to activate n8n workflow %s: HTTP %d", flow_id, resp.status_code,
            )
            return False

    async def delete_flow(self, flow_id: str) -> bool:
        """Delete a workflow by ID (best-effort cleanup)."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(
                f"{self.base_url}/api/v1/workflows/{flow_id}",
                headers=self._headers(),
            )
            if resp.is_success:
                logger.info("Deleted n8n workflow %s", flow_id)
                return True
            logger.debug("Could not delete n8n workflow %s: HTTP %d", flow_id, resp.status_code)
            return False

    async def trigger(self, flow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Trigger a workflow via its webhook URL.

        n8n webhooks with a "Respond to Webhook" node are synchronous:
        the HTTP response contains the workflow result directly.

        Note: *flow_id* here is the webhook path, not the numeric ID.
        """
        webhook_url = f"{self.base_url}/webhook/{flow_id}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()

        try:
            return resp.json()
        except Exception:
            return {"result": resp.text}

    async def get_run_status(self, run_id: str) -> dict[str, Any]:
        """Check execution status by ID."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/executions/{run_id}",
                headers=self._headers(),
            )
            if resp.status_code == 401:
                raise N8nError("n8n API key invalid or missing", status_code=401)
            resp.raise_for_status()

        data = resp.json()
        finished = data.get("finished", False)
        status = "completed" if finished else "running"
        if data.get("stoppedAt") and not finished:
            status = "failed"

        return {
            "status": status,
            "result": data.get("data", {}),
            "started_at": data.get("startedAt"),
            "stopped_at": data.get("stoppedAt"),
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _find_webhook_node(nodes: list[dict]) -> dict | None:
    """Return the first Webhook trigger node from a node list."""
    for node in nodes:
        node_type = node.get("type", "")
        if "webhook" in node_type.lower() and "respond" not in node_type.lower():
            return node
    return None


def _slugify(name: str) -> str:
    """Convert a display name to a URL-safe webhook path."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")
