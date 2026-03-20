"""STT model health checks and model discovery.

Execution is handled by execution/stt_executor.py — this module
provides admin-level operations only.
"""

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from src.db.models import STTModel


class STTError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def check_health(model: "STTModel") -> dict[str, Any]:
    """Run a health check against the STT model's server."""
    base_url = model.base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/v1/models")
            response.raise_for_status()
            return {"healthy": True, "base_url": base_url}
    except httpx.HTTPError as e:
        return {"healthy": False, "error": str(e)}


async def list_models(base_url: str) -> list[str]:
    """List available STT models from a server (for admin discovery UI)."""
    base_url = base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/v1/models")
            response.raise_for_status()
            data = response.json()
            return sorted([m["id"] for m in data.get("data", [])], key=str.lower)
    except httpx.HTTPError as e:
        raise STTError(f"Failed to list STT models: {e}")
