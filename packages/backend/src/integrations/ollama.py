"""Ollama LLM integration client."""

from typing import Any

import httpx

from src.config import get_settings


class OllamaError(Exception):
    """Error communicating with Ollama."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def list_models() -> list[dict[str, Any]]:
    """List available models from Ollama.

    Returns:
        List of model info dicts with at least a 'name' key.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except httpx.HTTPError as e:
            raise OllamaError(f"Failed to list models: {e}")


async def generate(
    model: str,
    prompt: str,
    temperature: float = 0.3,
    timeout: float = 120.0,
) -> str:
    """Generate text using an Ollama model.

    Args:
        model: Model name (e.g. 'mistral:7b')
        prompt: The full prompt to send
        temperature: Sampling temperature (0.0-1.0)
        timeout: Request timeout in seconds

    Returns:
        Generated text response.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
        except httpx.HTTPError as e:
            raise OllamaError(f"Generation failed: {e}")
