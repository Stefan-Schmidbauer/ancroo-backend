"""LLM model health checks and model discovery.

Execution is handled by execution/llm_executor.py — this module
provides admin-level operations only.
"""

from typing import TYPE_CHECKING, Any

import httpx

from src.crypto import decrypt_api_key
from src.integrations.llm_providers import get_api_format

if TYPE_CHECKING:
    from src.db.models import LLMModel


class LLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _build_headers(api_format: str, api_key: str | None) -> dict[str, str]:
    """Build auth headers based on the API format."""
    if not api_key:
        return {}
    if api_format == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    # openai format (Bearer token)
    return {"Authorization": f"Bearer {api_key}"}


async def check_health(model: "LLMModel") -> dict[str, Any]:
    """Run a health check against the LLM model's server."""
    base_url = model.base_url.rstrip("/")
    endpoint = model.endpoint_models.rstrip("/")
    url = f"{base_url}{endpoint}"
    api_key = decrypt_api_key(model.api_key)
    api_format = get_api_format(model.provider_type)

    headers = _build_headers(api_format, api_key)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return {"healthy": True, "base_url": base_url}
    except httpx.HTTPError as e:
        return {"healthy": False, "error": str(e)}


async def list_models(base_url: str, provider_type: str,
                      api_key: str | None = None,
                      endpoint_models: str | None = None) -> list[str]:
    """List available models from a server (for admin discovery UI)."""
    base_url = base_url.rstrip("/")
    api_format = get_api_format(provider_type)

    if endpoint_models:
        endpoint = endpoint_models.rstrip("/")
    else:
        # Fallback for probe-models (new model form, no DB row yet)
        from src.integrations.llm_providers import LLM_PROVIDERS_BY_KEY
        provider = LLM_PROVIDERS_BY_KEY.get(provider_type)
        endpoint = provider.default_endpoint_models if provider else "/v1/models"

    url = f"{base_url}{endpoint}"
    decrypted_key = decrypt_api_key(api_key)
    headers = _build_headers(api_format, decrypted_key)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

        if api_format == "ollama":
            return [m["name"] for m in data.get("models", [])]
        else:
            # Both Anthropic and OpenAI use {"data": [{"id": "..."}]}
            return [m["id"] for m in data.get("data", [])]
    except httpx.HTTPError as e:
        raise LLMError(f"Failed to list models: {e}")
