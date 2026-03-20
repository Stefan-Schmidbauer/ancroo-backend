"""SQLAlchemy database models for Ancroo."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """User model - synced from Keycloak via OIDC claims."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, comment="sub claim from OIDC provider"
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    groups: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, comment="Keycloak roles"
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    workflow_permissions: Mapped[list["WorkflowPermission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    hotkey_settings: Mapped[list["UserHotkeySetting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    execution_logs: Mapped[list["ExecutionLog"]] = relationship(back_populates="user")


# === Three-Area Model: LLM Models, STT Models, Tools ===


class LLMModel(Base):
    """Pre-configured LLM model entry (e.g. Mistral 7B on Ollama ROCm)."""

    __tablename__ = "llm_models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Display name, e.g. 'Mistral 7B (ROCm)'"
    )
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Provider key from llm_providers registry, e.g. 'ollama', 'anthropic', 'openai', 'openrouter', 'custom_openai'"
    )
    base_url: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="e.g. 'http://ollama-rocm:11434'"
    )
    endpoint_execute: Mapped[str] = mapped_column(
        String(255), nullable=False, default="/v1/chat/completions",
        comment="API path for execution, e.g. '/v1/chat/completions', '/v1/messages', '/api/generate'"
    )
    endpoint_models: Mapped[str] = mapped_column(
        String(255), nullable=False, default="/v1/models",
        comment="API path for model discovery/health, e.g. '/v1/models', '/api/tags'"
    )
    api_key: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="API key for OpenAI-compatible providers"
    )
    model_id: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Model identifier, e.g. 'mistral:7b', 'gpt-4o'"
    )
    default_temperature: Mapped[float] = mapped_column(
        Float, default=0.3,
        comment="Default temperature for generation"
    )
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="Extra provider-specific configuration"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(
        String(20), default="unknown",
        comment="'healthy', 'unhealthy', 'unknown'"
    )
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    workflows: Mapped[list["Workflow"]] = relationship(back_populates="llm_model")

    __table_args__ = (
        Index("idx_llm_models_active", "is_active", postgresql_where=text("is_active = true")),
    )


class STTModel(Base):
    """Pre-configured STT model entry (e.g. Whisper Large v3 on ROCm)."""

    __tablename__ = "stt_models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Display name, e.g. 'Whisper DE (ROCm)'"
    )
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="'whisper_openai_compatible'"
    )
    base_url: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="e.g. 'http://whisper-rocm:8000'"
    )
    api_key: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="API key for authenticated providers"
    )
    model_id: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Model identifier, e.g. 'openai/whisper-large-v3-turbo'"
    )
    default_language: Mapped[Optional[str]] = mapped_column(
        String(10),
        comment="Default ISO 639-1 language code (e.g. 'de'). Null = auto-detect."
    )
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="Extra provider-specific configuration"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="Default STT model for /api/v1/transcribe (only one should be true)"
    )
    health_status: Mapped[str] = mapped_column(
        String(20), default="unknown",
        comment="'healthy', 'unhealthy', 'unknown'"
    )
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    workflows: Mapped[list["Workflow"]] = relationship(back_populates="stt_model")

    __table_args__ = (
        Index("idx_stt_models_active", "is_active", postgresql_where=text("is_active = true")),
    )


class Tool(Base):
    """External tool entry (AR plugin, n8n webhook, or custom API)."""

    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Display name, e.g. 'HTML to Markdown'"
    )
    tool_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="'ar_plugin', 'n8n_webhook', 'custom_api'"
    )
    endpoint_url: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="Full URL, e.g. 'http://ancroo-runner:8000/convert/html-to-markdown'"
    )
    http_method: Mapped[str] = mapped_column(
        String(10), default="POST",
        comment="HTTP method for the endpoint"
    )
    headers: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="HTTP headers, e.g. {'Content-Type': 'application/json'}"
    )
    payload_template: Mapped[Optional[str]] = mapped_column(
        Text,
        comment="Jinja2 template for JSON body. Variables: text, html, url, title, fields, clipboard"
    )
    response_mapping: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="JSONPath for result extraction, e.g. '$.result'"
    )
    timeout: Mapped[int] = mapped_column(
        Integer, default=120,
        comment="Request timeout in seconds"
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    input_schema: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment="What the tool expects (from AR tool.yaml or n8n schema)"
    )
    output_schema: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment="What the tool returns"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(
        String(20), default="unknown",
        comment="'healthy', 'unhealthy', 'unknown'"
    )
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source: Mapped[Optional[str]] = mapped_column(
        String(50),
        comment="'auto_discovered', 'manual', 'imported'"
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="AR plugin name or n8n workflow ID for sync tracking"
    )
    # n8n-specific fields
    n8n_base_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="n8n instance URL for API operations (health check, flow management)"
    )
    n8n_api_key: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="n8n API key for management operations"
    )
    n8n_flow_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="n8n workflow ID (for provisioning and status checks)"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    workflows: Mapped[list["Workflow"]] = relationship(back_populates="tool")

    __table_args__ = (
        Index("idx_tools_type", "tool_type"),
        Index("idx_tools_active", "is_active", postgresql_where=text("is_active = true")),
        Index("idx_tools_source", "source", "source_id"),
    )


class Category(Base):
    """Workflow category — user-managed grouping with icon."""

    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="Display name, e.g. 'text', 'voice'"
    )
    icon: Mapped[str] = mapped_column(
        String(10), nullable=False, default="\U0001f527",
        comment="Emoji icon shown in UI"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    workflows: Mapped[list["Workflow"]] = relationship(back_populates="category_rel")


class Workflow(Base):
    """Workflow definition model — simplified: recipe → execution target → output action."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment="URL-friendly identifier"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"),
        comment="FK to categories table"
    )

    # Workflow type (determines which FK is used)
    workflow_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="'text_transformation', 'speech_to_text', 'tool'"
    )

    # === Execution target (exactly one of these three) ===

    # LLM model reference (for text_transformation workflows)
    llm_model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_models.id", ondelete="SET NULL"),
        comment="Pre-configured LLM model to use"
    )
    prompt_template: Mapped[Optional[str]] = mapped_column(
        Text,
        comment="Jinja2 prompt template. Variables: text, html, url, title, clipboard, fields"
    )
    temperature: Mapped[Optional[float]] = mapped_column(
        Float,
        comment="Temperature override (null = use model default)"
    )

    # STT model reference (for speech_to_text workflows)
    stt_model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stt_models.id", ondelete="SET NULL"),
        comment="Pre-configured STT model to use"
    )

    # Tool reference (for tool workflows — AR plugins, n8n webhooks, custom APIs)
    tool_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="SET NULL"),
        comment="Tool to execute"
    )

    # === Collection & Output ===

    # Collection Recipe — sent to extension (public)
    recipe: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="What the extension should collect: {collect: [...], form_fields: [...]}"
    )

    # Output action — sent to extension (public)
    output_action: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="'replace_selection', 'clipboard', 'notification', 'fill_fields', 'download_file', 'none'"
    )

    # === Configuration ===

    default_hotkey: Mapped[Optional[str]] = mapped_column(
        String(50), comment="e.g., 'Alt+Shift+G'"
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)

    # Demo page URL (relative path, served from static /demos mount)
    demo_url: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Relative path to demo page, e.g. 'demo.html'. Served at /demos/{slug}/{path}"
    )

    # === Metadata ===

    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # === Relationships ===

    category_rel: Mapped[Optional["Category"]] = relationship(back_populates="workflows")
    llm_model: Mapped[Optional["LLMModel"]] = relationship(back_populates="workflows")
    stt_model: Mapped[Optional["STTModel"]] = relationship(back_populates="workflows")
    tool: Mapped[Optional["Tool"]] = relationship(back_populates="workflows")
    permissions: Mapped[list["WorkflowPermission"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    hotkey_settings: Mapped[list["UserHotkeySetting"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    execution_logs: Mapped[list["ExecutionLog"]] = relationship(
        back_populates="workflow"
    )

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(llm_model_id, stt_model_id, tool_id) = 1",
            name="check_single_execution_target",
        ),
        Index("idx_workflows_slug", "slug"),
        Index("idx_workflows_category_id", "category_id"),
        Index("idx_workflows_llm_model", "llm_model_id"),
        Index("idx_workflows_stt_model", "stt_model_id"),
        Index("idx_workflows_tool", "tool_id"),
        Index("idx_workflows_active", "is_active", postgresql_where=text("is_active = true")),
    )


class WorkflowPermission(Base):
    """Workflow permission model - which users/groups can access which workflows."""

    __tablename__ = "workflow_permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )

    # Permission target (either user_id OR group_name, not both)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    group_name: Mapped[Optional[str]] = mapped_column(
        String(100), comment="Keycloak role name"
    )

    # Permission level
    permission_level: Mapped[str] = mapped_column(
        String(20), default="execute", comment="'execute', 'edit', 'admin'"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    workflow: Mapped["Workflow"] = relationship(back_populates="permissions")
    user: Mapped[Optional["User"]] = relationship(back_populates="workflow_permissions")

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND group_name IS NULL) OR "
            "(user_id IS NULL AND group_name IS NOT NULL)",
            name="check_permission_target",
        ),
        Index("idx_workflow_permissions_workflow", "workflow_id"),
        Index("idx_workflow_permissions_user", "user_id"),
        Index("idx_workflow_permissions_group", "group_name"),
    )


class ExecutionLog(Base):
    """Workflow execution log model."""

    __tablename__ = "execution_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL")
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # Execution details
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="'pending', 'running', 'success', 'error'"
    )
    input_preview: Mapped[Optional[str]] = mapped_column(
        Text, comment="First 200 chars of input (sanitized)"
    )
    output_preview: Mapped[Optional[str]] = mapped_column(
        Text, comment="First 200 chars of output"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)

    # Metadata
    client_version: Mapped[Optional[str]] = mapped_column(String(20))
    client_platform: Mapped[Optional[str]] = mapped_column(
        String(50), comment="'linux-x11', 'windows', etc."
    )

    # File upload metadata
    file_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Original filename of uploaded file"
    )
    file_size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Size of uploaded file in bytes"
    )

    # Relationships
    workflow: Mapped[Optional["Workflow"]] = relationship(back_populates="execution_logs")
    user: Mapped[Optional["User"]] = relationship(back_populates="execution_logs")

    __table_args__ = (
        Index("idx_execution_logs_user", "user_id"),
        Index("idx_execution_logs_workflow", "workflow_id"),
        Index("idx_execution_logs_started_at", "started_at"),
        Index("idx_execution_logs_workflow_started", "workflow_id", "started_at"),
    )


class UserHotkeySetting(Base):
    """User hotkey customization model."""

    __tablename__ = "user_hotkey_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    custom_hotkey: Mapped[Optional[str]] = mapped_column(
        String(50), comment="Overrides workflow default"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="hotkey_settings")
    workflow: Mapped["Workflow"] = relationship(back_populates="hotkey_settings")

    __table_args__ = (UniqueConstraint("user_id", "workflow_id"),)
