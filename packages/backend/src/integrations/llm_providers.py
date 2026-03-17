"""LLM provider registry — known providers with metadata.

Each provider defines a base URL and two endpoint paths (execute and
models).  These defaults are written into the ``LLMModel`` row when the
admin creates a new model entry.  The user can override any of them —
whatever is stored in the DB at save time is used at runtime.

Providers with ``api_format="openai"`` share the same code paths —
the provider key only affects UI labels and default URLs/endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LLMProvider:
    key: str
    label: str
    api_format: str  # "ollama" | "anthropic" | "openai"
    default_base_url: str
    default_endpoint_execute: str
    default_endpoint_models: str
    requires_api_key: bool


# Ordered list — determines dropdown order in admin UI.
LLM_PROVIDERS: list[LLMProvider] = [
    LLMProvider(
        key="ollama",
        label="Ollama",
        api_format="ollama",
        default_base_url="http://ollama:11434",
        default_endpoint_execute="/api/generate",
        default_endpoint_models="/api/tags",
        requires_api_key=False,
    ),
    LLMProvider(
        key="anthropic",
        label="Anthropic",
        api_format="anthropic",
        default_base_url="https://api.anthropic.com",
        default_endpoint_execute="/v1/messages",
        default_endpoint_models="/v1/models",
        requires_api_key=True,
    ),
    LLMProvider(
        key="openai",
        label="OpenAI",
        api_format="openai",
        default_base_url="https://api.openai.com",
        default_endpoint_execute="/v1/chat/completions",
        default_endpoint_models="/v1/models",
        requires_api_key=True,
    ),
    LLMProvider(
        key="openrouter",
        label="OpenRouter",
        api_format="openai",
        default_base_url="https://openrouter.ai/api",
        default_endpoint_execute="/v1/chat/completions",
        default_endpoint_models="/v1/models",
        requires_api_key=True,
    ),
    LLMProvider(
        key="deepseek",
        label="DeepSeek",
        api_format="openai",
        default_base_url="https://api.deepseek.com",
        default_endpoint_execute="/v1/chat/completions",
        default_endpoint_models="/v1/models",
        requires_api_key=True,
    ),
    LLMProvider(
        key="mistral",
        label="Mistral",
        api_format="openai",
        default_base_url="https://api.mistral.ai",
        default_endpoint_execute="/v1/chat/completions",
        default_endpoint_models="/v1/models",
        requires_api_key=True,
    ),
    LLMProvider(
        key="google",
        label="Google Gemini",
        api_format="openai",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_endpoint_execute="/v1/chat/completions",
        default_endpoint_models="/v1/models",
        requires_api_key=True,
    ),
    LLMProvider(
        key="groq",
        label="Groq",
        api_format="openai",
        default_base_url="https://api.groq.com/openai",
        default_endpoint_execute="/v1/chat/completions",
        default_endpoint_models="/v1/models",
        requires_api_key=True,
    ),
    LLMProvider(
        key="custom_openai",
        label="Custom (OpenAI-compatible)",
        api_format="openai",
        default_base_url="",
        default_endpoint_execute="/v1/chat/completions",
        default_endpoint_models="/v1/models",
        requires_api_key=False,
    ),
]

# Lookup by key.
LLM_PROVIDERS_BY_KEY: dict[str, LLMProvider] = {p.key: p for p in LLM_PROVIDERS}

# Valid provider_type values (for validation).
VALID_PROVIDER_TYPES: set[str] = {p.key for p in LLM_PROVIDERS}


def get_api_format(provider_type: str) -> str:
    """Return the API format for a provider_type, defaulting to ``openai``."""
    provider = LLM_PROVIDERS_BY_KEY.get(provider_type)
    return provider.api_format if provider else "openai"


def get_provider_label(provider_type: str) -> str:
    """Return the display label for a provider_type."""
    provider = LLM_PROVIDERS_BY_KEY.get(provider_type)
    return provider.label if provider else provider_type
