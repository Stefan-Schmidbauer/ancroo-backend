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
    """Workflow information response (sent to extension)."""

    id: UUID
    slug: str
    name: str
    description: Optional[str]
    category: Optional[str] = None
    category_icon: Optional[str] = None
    default_hotkey: Optional[str]
    version: str
    workflow_type: str
    recipe: Optional[dict[str, Any]] = None
    output_action: Optional[str] = None
    # Resolved names for display
    llm_model_name: Optional[str] = None
    stt_model_name: Optional[str] = None
    tool_name: Optional[str] = None

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
    prompt_template: Optional[str] = None
    temperature: Optional[float] = None
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


# LLM Model schemas


class LLMModelResponse(BaseModel):
    """LLM model information response."""

    id: UUID
    name: str
    provider_type: str
    base_url: str
    model_id: str
    default_temperature: float
    is_active: bool
    health_status: str = "unknown"
    last_health_check: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LLMModelListResponse(BaseModel):
    """List of LLM models."""

    models: list[LLMModelResponse]
    total: int


# STT Model schemas


class STTModelResponse(BaseModel):
    """STT model information response."""

    id: UUID
    name: str
    provider_type: str
    base_url: str
    model_id: str
    default_language: Optional[str] = None
    is_active: bool
    is_default: bool
    health_status: str = "unknown"
    last_health_check: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class STTModelListResponse(BaseModel):
    """List of STT models."""

    models: list[STTModelResponse]
    total: int


# Tool schemas


class ToolResponse(BaseModel):
    """Tool information response."""

    id: UUID
    name: str
    tool_type: str
    endpoint_url: str
    description: Optional[str] = None
    is_active: bool
    health_status: str = "unknown"
    last_health_check: Optional[datetime] = None
    source: Optional[str] = None
    source_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ToolListResponse(BaseModel):
    """List of tools."""

    tools: list[ToolResponse]
    total: int


class RunnerSyncResponse(BaseModel):
    """Result of AR plugin discovery sync."""

    created: int
    updated: int
    unchanged: int
    total: int
    errors: list[str] = Field(default_factory=list)


# System schemas


class HealthCheckResponse(BaseModel):
    """Health check result."""

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
