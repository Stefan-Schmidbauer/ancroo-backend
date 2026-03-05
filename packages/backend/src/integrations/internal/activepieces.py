"""Activepieces tool provider — implements ToolProvider protocol."""

import base64
import json
import logging
import time
from typing import Any

import httpx

from src.integrations.tool_provider import ToolProviderError

logger = logging.getLogger(__name__)

# Renew token 5 minutes before expiry
_TOKEN_RENEWAL_BUFFER_SECONDS = 300


class ActivepiecesError(ToolProviderError):
    """Error communicating with Activepieces."""

    pass


class ActivepiecesProvider:
    """Activepieces provider implementing the ToolProvider protocol.

    Supports: health check, flow discovery, webhook triggering, run status.

    Authentication priority:
    1. Static API key (api_key) — used as-is, no renewal
    2. Sign-in credentials (email/password) — auto-login, token cached and renewed
    """

    provider_type: str = "activepieces"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        email: str | None = None,
        password: str | None = None,
        config: dict | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._static_api_key = api_key
        self._email = email
        self._password = password
        self.config = config or {}
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0
        self._project_id: str | None = None

    async def _sign_in(self) -> str:
        """Authenticate via sign-in endpoint and return JWT token."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/authentication/sign-in",
                json={"email": self._email, "password": self._password},
            )

            if response.status_code != 200:
                raise ActivepiecesError(
                    f"Activepieces sign-in failed: {response.status_code} — {response.text}",
                    status_code=response.status_code,
                )

            data = response.json()
            token = data.get("token") or data.get("access_token")
            if not token:
                raise ActivepiecesError(
                    f"Sign-in response missing token field. Keys: {list(data.keys())}"
                )

            self._token_expires_at = self._parse_jwt_exp(token)
            self._cached_token = token
            self._project_id = data.get("projectId")
            logger.info(
                "Activepieces sign-in successful (project=%s), token expires at %s",
                self._project_id,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._token_expires_at)),
            )
            return token

    @staticmethod
    def _parse_jwt_exp(token: str) -> float:
        """Decode JWT payload (without verification) to read exp claim."""
        try:
            payload_b64 = token.split(".")[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp", 0)
            if exp:
                return float(exp)
        except (IndexError, ValueError, json.JSONDecodeError) as e:
            logger.warning("Could not parse JWT exp claim: %s", e)
        # Default: treat as valid for 1 hour
        return time.time() + 3600

    def _token_needs_renewal(self) -> bool:
        """Check if cached token is expired or about to expire."""
        if not self._cached_token:
            return True
        return time.time() >= (self._token_expires_at - _TOKEN_RENEWAL_BUFFER_SECONDS)

    async def _get_token(self) -> str | None:
        """Get a valid bearer token. Uses static key or auto-login."""
        if self._static_api_key:
            return self._static_api_key

        if self._email and self._password:
            if self._token_needs_renewal():
                return await self._sign_in()
            return self._cached_token

        return None

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_token()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def _has_auth(self) -> bool:
        """Check if any authentication method is configured."""
        return bool(self._static_api_key or (self._email and self._password))

    async def health_check(self) -> dict[str, Any]:
        """Check if Activepieces is reachable."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/flags",
                    headers=await self._auth_headers(),
                )
                if response.status_code == 200:
                    return {"healthy": True, "message": "Activepieces is reachable"}
                return {
                    "healthy": False,
                    "message": f"Unexpected status {response.status_code}",
                }
        except httpx.RequestError as e:
            return {"healthy": False, "message": f"Connection failed: {e}"}
        except ActivepiecesError as e:
            return {"healthy": False, "message": f"Auth failed: {e}"}

    async def discover_flows(self) -> list[dict[str, Any]]:
        """Discover available flows from Activepieces API.

        Returns flows that have webhook triggers (externally triggerable).
        """
        if not self._has_auth():
            raise ActivepiecesError(
                "Activepieces authentication not configured — "
                "set API key or email/password credentials"
            )

        # Ensure we have a token (and thus projectId) before making the request
        await self._get_token()

        params: dict[str, Any] = {"limit": 100}
        if self._project_id:
            params["projectId"] = self._project_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/flows",
                headers=await self._auth_headers(),
                params=params,
            )

            if response.status_code == 401:
                # Token might have been invalidated server-side — force renewal
                if self._email and self._password:
                    self._cached_token = None
                    await self._get_token()
                    if self._project_id:
                        params["projectId"] = self._project_id
                    response = await client.get(
                        f"{self.base_url}/api/v1/flows",
                        headers=await self._auth_headers(),
                        params=params,
                    )

            if response.status_code != 200:
                raise ActivepiecesError(
                    f"Failed to list flows: {response.status_code}",
                    status_code=response.status_code,
                )

            data = response.json()
            raw_flows = data.get("data", data if isinstance(data, list) else [])

            flows = []
            for flow in raw_flows:
                trigger = flow.get("version", {}).get("trigger", {})
                trigger_type = trigger.get("type", "")

                flows.append({
                    "id": flow.get("id", ""),
                    "name": flow.get("version", {}).get("displayName", flow.get("id", "Unknown")),
                    "description": flow.get("version", {}).get("description", ""),
                    "status": flow.get("status", "ENABLED"),
                    "trigger_type": trigger_type,
                    "has_webhook": trigger_type in ("WEBHOOK", "PIECE_TRIGGER"),
                    "webhook_url": self._build_webhook_url(flow) if trigger_type == "WEBHOOK" else None,
                    "created": flow.get("created", ""),
                    "updated": flow.get("updated", ""),
                })

            return flows

    def _build_webhook_url(self, flow: dict) -> str | None:
        """Build synchronous webhook URL for a flow.

        Uses the /sync suffix so Activepieces waits for a "Return Response"
        step and sends the result back in the HTTP response.
        """
        flow_id = flow.get("id")
        if not flow_id:
            return None
        return f"{self.base_url}/api/v1/webhooks/{flow_id}/sync"

    async def _get_piece_count(self) -> int:
        """Return the number of pieces in AP's piece cache.

        Used to detect whether AP's initial piece sync has completed.
        A fresh AP instance starts with 0 pieces in the cache; after the
        background sync the count grows to several thousand.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/pieces",
                    headers=await self._auth_headers(),
                    params={"limit": "500"},
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        return len(data)
                    return data.get("total", len(data.get("data", [])))
        except Exception as e:
            logger.debug("Could not query piece count: %s", e)
        return 0

    async def _get_webhook_piece_version(self) -> str:
        """Query AP for the installed version of @activepieces/piece-webhook.

        Falls back to a sensible default if the query fails.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/pieces",
                    headers=await self._auth_headers(),
                    params={"searchQuery": "webhook"},
                )
                if response.status_code == 200:
                    data = response.json()
                    pieces = data if isinstance(data, list) else data.get("data", [])
                    for piece in pieces:
                        if piece.get("name") == "@activepieces/piece-webhook":
                            version = piece.get("version", "")
                            if version:
                                logger.info("Detected piece-webhook version: %s", version)
                                return version
        except Exception as e:
            logger.debug("Could not query piece-webhook version: %s", e)

        return "~0.1.0"

    async def find_flow_by_name(self, display_name: str) -> dict[str, Any] | None:
        """Find an existing flow by display name.

        Returns the flow dict if found, None otherwise.
        """
        try:
            flows = await self.discover_flows()
            for flow in flows:
                if flow.get("name") == display_name:
                    return flow
        except Exception as e:
            logger.debug("Could not search for existing flow '%s': %s", display_name, e)
        return None

    async def delete_flow(self, flow_id: str) -> bool:
        """Delete a flow by ID. Returns True on success."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.delete(
                    f"{self.base_url}/api/v1/flows/{flow_id}",
                    headers=await self._auth_headers(),
                )
                return response.status_code in (200, 204)
        except Exception as e:
            logger.debug("Could not delete flow %s: %s", flow_id, e)
            return False

    async def create_webhook_flow(self, display_name: str) -> dict[str, Any]:
        """Create a new flow with a Catch Webhook trigger.

        Creates a blank flow, then applies the PIECE_TRIGGER via UPDATE_TRIGGER.
        The IMPORT_FLOW operation does not reliably set the trigger in AP >= 0.78.

        If a flow with the same display name already exists, it is deleted first
        to prevent duplicate flows from accumulating after failed provisioning.

        Returns:
            dict with keys: flow_id, flow_version_id, webhook_url
        """
        if not self._has_auth():
            raise ActivepiecesError("Activepieces authentication not configured")

        await self._get_token()

        # Clean up any existing flow with the same name (orphan from failed attempt)
        existing = await self.find_flow_by_name(display_name)
        if existing:
            old_id = existing.get("id")
            logger.info(
                "Deleting existing AP flow '%s' (%s) before re-creating",
                display_name, old_id,
            )
            await self.delete_flow(old_id)

        # Detect installed piece-webhook version dynamically
        webhook_piece_version = await self._get_webhook_piece_version()

        # Step 1: Create blank flow (projectId must be in the body)
        create_body: dict[str, Any] = {
            "displayName": display_name,
            "projectId": self._project_id,
            "type": "IMPORT_FLOW",
            "flow": {
                "version": {
                    "displayName": display_name,
                    "schemaVersion": 16,
                    "trigger": {
                        "name": "trigger",
                        "type": "EMPTY",
                        "valid": False,
                        "displayName": "Select Trigger",
                        "settings": {},
                    },
                    "connectionIds": [],
                    "agentIds": [],
                    "valid": False,
                }
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/flows",
                headers=await self._auth_headers(),
                json=create_body,
            )

            if response.status_code not in (200, 201):
                raise ActivepiecesError(
                    f"Failed to create flow: {response.status_code} — {response.text[:200]}",
                    status_code=response.status_code,
                )

            data = response.json()
            flow_id = data.get("id", "")

            # Step 2: Set the webhook trigger via UPDATE_TRIGGER
            trigger_body = {
                "type": "UPDATE_TRIGGER",
                "request": {
                    "name": "trigger",
                    "type": "PIECE_TRIGGER",
                    "valid": True,
                    "displayName": "Catch Webhook",
                    "settings": {
                        "pieceName": "@activepieces/piece-webhook",
                        "pieceVersion": webhook_piece_version,
                        "triggerName": "catch_webhook",
                        "input": {
                            "authType": "none",
                            "authFields": {},
                        },
                        "sampleData": {},
                        "propertySettings": {},
                    },
                },
            }
            response = await client.post(
                f"{self.base_url}/api/v1/flows/{flow_id}",
                headers=await self._auth_headers(),
                json=trigger_body,
            )

            if response.status_code not in (200, 201):
                # Clean up the blank flow to avoid accumulating disabled stubs.
                try:
                    await client.delete(
                        f"{self.base_url}/api/v1/flows/{flow_id}",
                        headers=await self._auth_headers(),
                    )
                except Exception:
                    pass  # Best-effort cleanup
                raise ActivepiecesError(
                    f"Failed to set webhook trigger: {response.status_code} — {response.text[:200]}",
                    status_code=response.status_code,
                )

            data = response.json()

            # Step 3: Add "Return Response" action so /sync returns immediately
            # Without this step, AP waits the full AP_WEBHOOK_TIMEOUT_SECONDS
            # before returning because no step terminates the sync request.
            action_body = {
                "type": "ADD_ACTION",
                "request": {
                    "name": "return_response",
                    "type": "PIECE_ACTION",
                    "valid": True,
                    "displayName": "Return Response",
                    "settings": {
                        "pieceName": "@activepieces/piece-webhook",
                        "pieceVersion": webhook_piece_version,
                        "actionName": "return_response",
                        "input": {
                            "status": 200,
                            "body": "{{ trigger.body }}",
                            "headers": {},
                        },
                        "propertySettings": {},
                    },
                },
            }
            response = await client.post(
                f"{self.base_url}/api/v1/flows/{flow_id}",
                headers=await self._auth_headers(),
                json=action_body,
            )

            if response.status_code not in (200, 201):
                try:
                    await client.delete(
                        f"{self.base_url}/api/v1/flows/{flow_id}",
                        headers=await self._auth_headers(),
                    )
                except Exception:
                    pass
                raise ActivepiecesError(
                    f"Failed to add Return Response action: {response.status_code} — {response.text[:200]}",
                    status_code=response.status_code,
                )

            data = response.json()
            flow_version_id = data.get("version", {}).get("id", "")

            return {
                "flow_id": flow_id,
                "flow_version_id": flow_version_id,
                "webhook_url": f"{self.base_url}/api/v1/webhooks/{flow_id}/sync",
            }

    async def publish_flow(self, flow_id: str, flow_version_id: str) -> bool:
        """Lock and publish a flow version so it becomes active.

        Args:
            flow_id: The flow ID
            flow_version_id: The flow version ID to publish

        Returns:
            True if successful
        """
        if not self._has_auth():
            raise ActivepiecesError("Activepieces authentication not configured")

        await self._get_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/flows/{flow_id}",
                headers=await self._auth_headers(),
                json={
                    "type": "LOCK_AND_PUBLISH",
                    "request": {"flowVersionId": flow_version_id},
                },
            )

            if response.status_code not in (200, 201):
                logger.warning(
                    "Flow publish returned %s for flow %s: %s",
                    response.status_code, flow_id, response.text[:200],
                )
                return False

            logger.info("Published flow %s", flow_id)
            return True

    async def enable_flow(self, flow_id: str) -> bool:
        """Enable a flow so its webhook listener is registered.

        Args:
            flow_id: The flow ID to enable

        Returns:
            True if successful
        """
        if not self._has_auth():
            raise ActivepiecesError("Activepieces authentication not configured")

        await self._get_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/flows/{flow_id}",
                headers=await self._auth_headers(),
                json={
                    "type": "CHANGE_STATUS",
                    "request": {"status": "ENABLED"},
                },
            )

            if response.status_code not in (200, 201):
                logger.warning(
                    "Flow enable returned %s for flow %s: %s",
                    response.status_code, flow_id, response.text[:200],
                )
                return False

            logger.info("Enabled flow %s (webhook registered)", flow_id)
            return True

    async def trigger(self, flow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Trigger an Activepieces flow via webhook.

        Args:
            flow_id: The flow ID or full webhook URL
            payload: Data to send to the webhook
        """
        # Support both full URL and flow ID.
        # Use /sync suffix so Activepieces returns the "Return Response" output.
        if flow_id.startswith("http"):
            webhook_url = flow_id
        else:
            webhook_url = f"{self.base_url}/api/v1/webhooks/{flow_id}/sync"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(webhook_url, json=payload)

            if response.status_code not in (200, 201):
                raise ActivepiecesError(
                    f"Webhook trigger failed with status {response.status_code}",
                    status_code=response.status_code,
                )

            try:
                return response.json()
            except Exception:
                return {"raw_response": response.text}

    async def get_run_status(self, run_id: str) -> dict[str, Any]:
        """Check the status of a flow run."""
        if not self._has_auth():
            raise ActivepiecesError(
                "Activepieces authentication not configured — "
                "set API key or email/password credentials"
            )

        await self._get_token()

        params: dict[str, str] = {}
        if self._project_id:
            params["projectId"] = self._project_id

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/flow-runs/{run_id}",
                headers=await self._auth_headers(),
                params=params,
            )

            if response.status_code == 401 and self._email and self._password:
                self._cached_token = None
                await self._get_token()
                if self._project_id:
                    params["projectId"] = self._project_id
                response = await client.get(
                    f"{self.base_url}/api/v1/flow-runs/{run_id}",
                    headers=await self._auth_headers(),
                    params=params,
                )

            if response.status_code != 200:
                raise ActivepiecesError(
                    f"Failed to get run status: {response.status_code}",
                    status_code=response.status_code,
                )

            data = response.json()
            return {
                "status": data.get("status", "UNKNOWN").lower(),
                "result": data.get("output", {}),
                "duration_ms": data.get("duration"),
            }


# Backward-compatible alias
class ActivepiecesClient(ActivepiecesProvider):
    """Legacy alias for ActivepiecesProvider."""

    def __init__(self):
        from src.config import get_settings
        settings = get_settings()
        super().__init__(
            base_url=settings.activepieces_url,
            api_key=settings.activepieces_api_key,
            email=settings.activepieces_email,
            password=settings.activepieces_password,
        )

    async def trigger_workflow(self, webhook_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Legacy method — delegates to trigger()."""
        return await self.trigger(webhook_url, payload)
