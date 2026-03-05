"""Tool provider protocol for external workflow tools."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolProvider(Protocol):
    """Protocol for external workflow tool providers.

    Implementations: N8nProvider, etc.
    """

    provider_type: str

    async def health_check(self) -> dict[str, Any]:
        """Check if the provider is reachable.

        Returns:
            {"healthy": True/False, "message": "...", "details": {...}}
        """
        ...

    async def discover_flows(self) -> list[dict[str, Any]]:
        """Discover available flows/workflows in the external tool.

        Returns:
            List of flow dicts with at least: id, name, description, status
        """
        ...

    async def trigger(self, flow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Trigger a flow and return the result.

        Args:
            flow_id: The external flow identifier
            payload: Input data to send to the flow

        Returns:
            Raw response from the external tool
        """
        ...

    async def get_run_status(self, run_id: str) -> dict[str, Any]:
        """Check the status of a running flow (optional).

        Args:
            run_id: The flow run identifier

        Returns:
            {"status": "running"|"completed"|"failed", "result": {...}}
        """
        ...


class ToolProviderError(Exception):
    """Base error for tool provider operations."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)
