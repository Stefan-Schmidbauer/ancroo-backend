"""LLM provider clients and runtime target resolver.

Supported provider types:
  - "ollama"            — Ollama /api/generate + /api/tags
  - "openai_compatible" — OpenAI-format /v1/chat/completions + /v1/models
                          Works with: local Ollama (/v1 endpoint), LM Studio, vLLM,
                          cloud OpenAI, and any compatible API.
"""

import json
from typing import TYPE_CHECKING, Any

import httpx

from src.crypto import decrypt_api_key

if TYPE_CHECKING:
    from src.db.models import LLMProvider


class LLMProviderError(Exception):
    """Error communicating with an LLM provider."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------


async def _ollama_health_check(base_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            return {"healthy": True, "provider_type": "ollama", "base_url": base_url}
        except httpx.HTTPError as e:
            return {"healthy": False, "error": str(e)}


async def _ollama_list_models(base_url: str) -> list[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except httpx.HTTPError as e:
            raise LLMProviderError(f"Failed to list Ollama models: {e}")


def _ollama_build_target(
    base_url: str,
    model: str,
    prompt_template: str,
    temperature: float,
    timeout: int,
) -> dict[str, Any]:
    """Build a full target_config dict for an Ollama /api/generate call."""
    payload_template = json.dumps({
        "model": model,
        "prompt": "PROMPT_PLACEHOLDER",
        "stream": False,
        "options": {"temperature": temperature},
    }).replace('"PROMPT_PLACEHOLDER"', json.dumps(prompt_template))

    return {
        "url": f"{base_url.rstrip('/')}/api/generate",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "payload_template": payload_template,
        "response_mapping": "$.response",
        "timeout": timeout,
    }


# ---------------------------------------------------------------------------
# OpenAI-compatible client
# ---------------------------------------------------------------------------


async def _openai_health_check(base_url: str, api_key: str | None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{base_url.rstrip('/')}/v1/models", headers=headers
            )
            response.raise_for_status()
            return {
                "healthy": True,
                "provider_type": "openai_compatible",
                "base_url": base_url,
            }
        except httpx.HTTPError as e:
            return {"healthy": False, "error": str(e)}


async def _openai_list_models(base_url: str, api_key: str | None) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{base_url.rstrip('/')}/v1/models", headers=headers
            )
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except httpx.HTTPError as e:
            raise LLMProviderError(f"Failed to list models: {e}")


def _openai_build_target(
    base_url: str,
    api_key: str | None,
    model: str,
    prompt_template: str,
    temperature: float,
    timeout: int,
) -> dict[str, Any]:
    """Build a full target_config dict for an OpenAI-compatible chat/completions call."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Jinja2 template that renders the user prompt and embeds it in the OpenAI payload
    messages_template = json.dumps([{"role": "user", "content": "PROMPT_PLACEHOLDER"}]).replace(
        '"PROMPT_PLACEHOLDER"', json.dumps(prompt_template)
    )
    payload_template = json.dumps({
        "model": model,
        "messages": "MESSAGES_PLACEHOLDER",
        "temperature": temperature,
        "stream": False,
    }).replace('"MESSAGES_PLACEHOLDER"', messages_template)

    return {
        "url": f"{base_url.rstrip('/')}/v1/chat/completions",
        "method": "POST",
        "headers": headers,
        "payload_template": payload_template,
        "response_mapping": "$.choices[0].message.content",
        "timeout": timeout,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_provider_health(provider: "LLMProvider") -> dict[str, Any]:
    """Run a health check against the given LLM provider."""
    if provider.provider_type == "ollama":
        return await _ollama_health_check(provider.base_url)
    elif provider.provider_type == "openai_compatible":
        return await _openai_health_check(provider.base_url, decrypt_api_key(provider.api_key))
    else:
        return {"healthy": False, "error": f"Unknown provider type: {provider.provider_type}"}


async def list_provider_models(provider: "LLMProvider") -> list[str]:
    """List available models from the given LLM provider."""
    if provider.provider_type == "ollama":
        return await _ollama_list_models(provider.base_url)
    elif provider.provider_type == "openai_compatible":
        return await _openai_list_models(provider.base_url, decrypt_api_key(provider.api_key))
    else:
        raise LLMProviderError(f"Unknown provider type: {provider.provider_type}")


def build_runtime_target(
    provider: "LLMProvider",
    llm_model: str | None,
    workflow_target_config: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the full HTTP target_config for a workflow at execution time.

    Called by http_executor when workflow.llm_provider_id is set.
    The workflow's target_config is expected to contain at minimum:
      _prompt_template: Jinja2 template string with {{ text }}, etc.
      _temperature: float (default 0.3)
      timeout: int (default 120)

    Returns a complete target_config dict ready for http_executor.
    """
    model = llm_model or provider.default_model
    if not model:
        raise LLMProviderError(
            "No model specified: workflow has no model override and provider has no default model"
        )
    prompt_template = workflow_target_config.get("_prompt_template", "{{ text }}")
    temperature = float(workflow_target_config.get("_temperature", 0.3))
    timeout = int(workflow_target_config.get("timeout", 120))

    if provider.provider_type == "ollama":
        return _ollama_build_target(
            provider.base_url, model, prompt_template, temperature, timeout
        )
    elif provider.provider_type == "openai_compatible":
        return _openai_build_target(
            provider.base_url, decrypt_api_key(provider.api_key), model, prompt_template, temperature, timeout
        )
    else:
        raise LLMProviderError(
            f"Cannot build runtime target for unknown provider type: {provider.provider_type}"
        )
