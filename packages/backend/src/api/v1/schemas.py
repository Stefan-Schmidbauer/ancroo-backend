"""Pydantic schemas for API requests and responses."""

from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field


# Auth schemas


class LoginInitResponse(BaseModel):
    """Response for login initiation."""

    authorization_url: str
    state: str
    code_verifier: str  # Client needs to store this for callback


class TokenCallbackRequest(BaseModel):
    """Request for token callback."""

    code: str
    state: str
    code_verifier: str
    redirect_uri: str


class TokenResponse(BaseModel):
    """Token response."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Request to refresh access token."""

    refresh_token: str


class UserResponse(BaseModel):
    """User information response."""

    id: UUID
    email: str
    display_name: Optional[str]
    groups: list[str]
    is_admin: bool

    class Config:
        from_attributes = True


# Workflow schemas


class WorkflowResponse(BaseModel):
    """Workflow information response."""

    id: UUID
    slug: str
    name: str
    description: Optional[str]
    category: Optional[str]
    default_hotkey: Optional[str]
    input_type: str
    output_type: str
    execution_type: str = "script"
    version: str
    provider_name: Optional[str] = None
    llm_provider_name: Optional[str] = None
    stt_provider_name: Optional[str] = None
    sync_status: str = "manual"
    # New generic fields (public — sent to extension)
    workflow_type: Optional[str] = None
    recipe: Optional[dict[str, Any]] = None
    output_action: Optional[str] = None
    # NOTE: target_config is intentionally NOT included (private, stays on server)

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    """List of workflows response."""

    workflows: list[WorkflowResponse]
    total: int
    synced_at: datetime


class WorkflowDetailResponse(WorkflowResponse):
    """Detailed workflow response."""

    timeout_seconds: int
    created_at: datetime
    updated_at: datetime


# Execution schemas


class ExecutionInput(BaseModel):
    """Input data for workflow execution."""

    text: Optional[str] = None
    html: Optional[str] = None
    clipboard: Optional[str] = None
    fields: Optional[dict[str, str]] = None
    context: dict[str, Any] = Field(default_factory=dict)


class ExecuteWorkflowRequest(BaseModel):
    """Request to execute a workflow."""

    input_data: ExecutionInput
    client_script_result: Optional[dict[str, Any]] = None
    client_version: Optional[str] = None
    client_platform: Optional[str] = None


class ExecutionResult(BaseModel):
    """Result from workflow execution."""

    text: Optional[str] = None
    action: str = "replace_selection"
    success: bool = True
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecuteWorkflowResponse(BaseModel):
    """Response from workflow execution."""

    execution_id: UUID
    status: str
    result: Optional[ExecutionResult]
    duration_ms: Optional[int]


# Hotkey schemas


class HotkeySettingResponse(BaseModel):
    """User hotkey setting response."""

    workflow_id: UUID
    workflow_slug: str
    workflow_name: str
    hotkey: str  # Custom or default
    is_enabled: bool

    class Config:
        from_attributes = True


class UpdateHotkeyRequest(BaseModel):
    """Request to update hotkey setting."""

    workflow_id: UUID
    custom_hotkey: Optional[str] = None
    is_enabled: bool = True


# Tool Provider schemas


class ToolProviderResponse(BaseModel):
    """Tool provider information response."""

    id: UUID
    provider_type: str
    name: str
    base_url: str
    is_active: bool
    health_status: str = "unknown"
    last_health_check: Optional[datetime] = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ToolProviderListResponse(BaseModel):
    """List of tool providers."""

    providers: list[ToolProviderResponse]
    total: int


class CreateToolProviderRequest(BaseModel):
    """Request to register a new tool provider."""

    provider_type: str
    name: str
    base_url: str
    api_key: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class UpdateToolProviderRequest(BaseModel):
    """Request to update a tool provider."""

    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class DiscoveredFlowResponse(BaseModel):
    """A flow discovered from an external tool provider."""

    id: str
    name: str
    description: str = ""
    status: str = "ENABLED"
    trigger_type: str = ""
    has_webhook: bool = False
    already_imported: bool = False


class DiscoverFlowsResponse(BaseModel):
    """List of discovered flows from a provider."""

    provider_id: UUID
    provider_name: str
    flows: list[DiscoveredFlowResponse]
    total: int


class ImportFlowRequest(BaseModel):
    """Request to import a flow as an Ancroo workflow."""

    flow_id: str
    flow_name: str
    category: str = "tool"
    input_type: str = "text_selection"
    output_type: str = "clipboard"


class SyncResultResponse(BaseModel):
    """Result of a workflow sync operation."""

    synced: int
    updated: int
    missing: int
    total: int


class HealthCheckResponse(BaseModel):
    """Health check result for a tool provider."""

    healthy: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AboutResponse(BaseModel):
    """Application version and metadata."""

    name: str
    description: str
    version: str
    commit: str
    author: str
    license: str
    repository: str
