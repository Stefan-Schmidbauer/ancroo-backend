"""STT provider clients and runtime target resolver.

Supported provider types:
  - "whisper_openai_compatible" — OpenAI-format /v1/audio/transcriptions + /v1/models
                                  Works with: Speaches, Whisper-ROCm, faster-whisper-server,
                                  and any compatible Whisper API.
"""

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from src.db.models import STTProvider


class STTProviderError(Exception):
    """Error communicating with an STT provider."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Whisper OpenAI-compatible client
# ---------------------------------------------------------------------------


async def _whisper_health_check(base_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{base_url.rstrip('/')}/v1/models")
            response.raise_for_status()
            return {
                "healthy": True,
                "provider_type": "whisper_openai_compatible",
                "base_url": base_url,
            }
        except httpx.HTTPError as e:
            return {"healthy": False, "error": str(e)}


async def _whisper_list_models(base_url: str) -> list[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{base_url.rstrip('/')}/v1/models")
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except httpx.HTTPError as e:
            raise STTProviderError(f"Failed to list STT models: {e}")


def _whisper_build_target(
    base_url: str,
    model: str,
    language: str | None,
    timeout: int,
) -> dict[str, Any]:
    """Build a full target_config dict for an OpenAI-compatible transcriptions call."""
    form_fields: dict[str, str] = {"model": model}
    if language:
        form_fields["language"] = language

    return {
        "url": f"{base_url.rstrip('/')}/v1/audio/transcriptions",
        "method": "POST",
        "file_field_name": "file",
        "form_fields": form_fields,
        "response_mapping": "$.text",
        "timeout": timeout,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_provider_health(provider: "STTProvider") -> dict[str, Any]:
    """Run a health check against the given STT provider."""
    if provider.provider_type == "whisper_openai_compatible":
        return await _whisper_health_check(provider.base_url)
    else:
        return {"healthy": False, "error": f"Unknown provider type: {provider.provider_type}"}


async def list_provider_models(provider: "STTProvider") -> list[str]:
    """List available models from the given STT provider."""
    if provider.provider_type == "whisper_openai_compatible":
        return await _whisper_list_models(provider.base_url)
    else:
        raise STTProviderError(f"Unknown provider type: {provider.provider_type}")


def build_runtime_stt_target(
    provider: "STTProvider",
    stt_model: str | None,
    workflow_target_config: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the full HTTP target_config for an STT workflow at execution time.

    Called by http_executor when workflow.stt_provider_id is set.
    The workflow's target_config is expected to contain at minimum:
      _preset: "stt" or "whisper"
      _language: optional language code
      timeout: int (default 120)

    Returns a complete target_config dict ready for http_executor.
    """
    model = stt_model or provider.default_model
    raw_lang = workflow_target_config.get("_language") or None
    language = None if raw_lang and raw_lang.lower() == "none" else raw_lang
    timeout = int(workflow_target_config.get("timeout", 120))

    if provider.provider_type == "whisper_openai_compatible":
        return _whisper_build_target(provider.base_url, model, language, timeout)
    else:
        raise STTProviderError(
            f"Cannot build runtime target for unknown provider type: {provider.provider_type}"
        )
