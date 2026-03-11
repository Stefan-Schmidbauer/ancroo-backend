"""Convenience presets for common workflow targets.

These functions convert simple admin inputs (model + prompt, flow selection)
into the generic target_config format used by the HTTP executor.
"""

import json

from src.config import get_settings


def build_llm_target(
    prompt_template: str,
    temperature: float = 0.3,
    timeout: int = 120,
) -> dict:
    """Build target_config for a provider-backed LLM workflow.

    The provider URL and model are resolved at execution time from
    workflow.llm_provider_id and workflow.llm_model.

    Args:
        prompt_template: Jinja2 prompt with {{ text }}, {{ url }}, {{ title }}
        temperature: Sampling temperature (0.0-1.0)
        timeout: Request timeout in seconds

    Returns:
        target_config dict ready for storage.
    """
    return {
        "_preset": "llm",
        "_prompt_template": prompt_template,
        "_temperature": temperature,
        "timeout": timeout,
    }


def build_n8n_target(webhook_url: str) -> dict:
    """Build target_config for an n8n webhook trigger.

    Used by: Workflow-Trigger workflow type (n8n).

    Args:
        webhook_url: Full webhook URL for the n8n workflow

    Returns:
        target_config dict ready for storage.
    """
    return {
        "url": webhook_url,
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "payload_template": "{{ _input | tojson }}",
        "response_mapping": "$.result",
        "timeout": 120,
        "_preset": "n8n",
    }


def build_whisper_target(
    model: str | None = None,
    language: str | None = None,
    url: str | None = None,
) -> dict:
    """Build target_config for Whisper STT (OpenAI-compatible API).

    Used by: Audio transcription workflows.
    Admin provides: optional model, language, and server URL override.
    This generates the full HTTP config for the /v1/audio/transcriptions endpoint.

    Args:
        model: Whisper model name (e.g. 'Systran/faster-whisper-large-v3').
               Defaults to settings.whisper_model.
        language: ISO 639-1 language code (e.g. 'de', 'en'). Auto-detect if omitted.
        url: Base URL override (e.g. 'http://speaches:8100').
             Defaults to settings.whisper_base_url.

    Returns:
        target_config dict ready for storage.
    """
    settings = get_settings()

    resolved_model = model or settings.whisper_model
    resolved_base_url = url.rstrip("/") if url else settings.whisper_base_url
    form_fields: dict[str, str] = {"model": resolved_model}
    if language:
        form_fields["language"] = language

    return {
        "url": f"{resolved_base_url}/v1/audio/transcriptions",
        "method": "POST",
        "file_field_name": "file",
        "form_fields": form_fields,
        "response_mapping": "$.text",
        "timeout": 120,
        "_preset": "whisper",
        "_model": resolved_model,
        "_language": language,
        "_url": url or "",
    }


def build_stt_target(
    language: str | None = None,
    timeout: int = 120,
) -> dict:
    """Build target_config for a provider-backed STT workflow.

    Unlike build_whisper_target, this does NOT bake in the provider URL or model.
    Those are resolved at execution time from workflow.stt_provider_id and
    workflow.stt_model.

    Use this when creating workflows that reference an STTProvider in the DB.

    Args:
        language: ISO 639-1 language code (e.g. 'de', 'en'). Auto-detect if omitted.
        timeout: Request timeout in seconds

    Returns:
        target_config dict ready for storage.
    """
    return {
        "_preset": "stt",
        "_language": language or None,
        "timeout": timeout,
    }


def build_recipe(
    sources: list[str],
    form_fields: list[dict] | None = None,
    output_fields: list[dict] | None = None,
    file_config: dict | None = None,
) -> dict:
    """Build a collection recipe for the extension.

    Args:
        sources: List of input sources to collect
                 Valid: 'text_selection', 'clipboard', 'form_fields',
                        'page_context', 'file', 'audio'
        form_fields: Optional list of form field definitions
                     Each: {'name': str, 'selector': str}
        output_fields: Optional list of output field definitions for fill_fields action
                       Each: {'name': str, 'selector': str}
        file_config: Optional file/audio upload config
                     Keys: 'accept', 'max_size_mb', 'label', 'required'

    Returns:
        Recipe dict for the extension.
    """
    recipe = {"collect": sources}
    if form_fields and "form_fields" in sources:
        recipe["form_fields"] = form_fields
    if output_fields:
        recipe["output_fields"] = output_fields
    if file_config and ("file" in sources or "audio" in sources):
        recipe["file_config"] = file_config
    return recipe
