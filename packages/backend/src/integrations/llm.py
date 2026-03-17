"""LLM model health checks and model discovery.

Execution is handled by execution/llm_executor.py — this module
provides admin-level operations only.
"""

from typing import TYPE_CHECKING, Any

import httpx

from src.crypto import decrypt_api_key

if TYPE_CHECKING:
    from src.db.models import LLMModel


class LLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def check_health(model: "LLMModel") -> dict[str, Any]:
    """Run a health check against the LLM model's server."""
    base_url = model.base_url.rstrip("/")
    api_key = decrypt_api_key(model.api_key)

    if model.provider_type == "ollama":
        url = f"{base_url}/api/tags"
        headers = {}
    else:
        url = f"{base_url}/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return {"healthy": True, "base_url": base_url}
    except httpx.HTTPError as e:
        return {"healthy": False, "error": str(e)}


async def list_models(base_url: str, provider_type: str, api_key: str | None = None) -> list[str]:
    """List available models from a server (for admin discovery UI)."""
    base_url = base_url.rstrip("/")
    decrypted_key = decrypt_api_key(api_key)

    if provider_type == "ollama":
        url = f"{base_url}/api/tags"
        headers = {}
    else:
        url = f"{base_url}/v1/models"
        headers = {"Authorization": f"Bearer {decrypted_key}"} if decrypted_key else {}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

        if provider_type == "ollama":
            return [m["name"] for m in data.get("models", [])]
        else:
            return [m["id"] for m in data.get("data", [])]
    except httpx.HTTPError as e:
        raise LLMError(f"Failed to list models: {e}")
