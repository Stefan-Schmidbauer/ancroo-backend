"""SQLAlchemy database models for Ancroo."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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


class ToolProvider(Base):
    """External tool provider registration (e.g. Activepieces, n8n)."""

    __tablename__ = "tool_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="'n8n', 'custom_api', etc."
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Display name, e.g. 'n8n Production'"
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(
        String(500), comment="API key for authentication"
    )
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="Provider-specific additional configuration"
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
    workflows: Mapped[list["Workflow"]] = relationship(
        back_populates="tool_provider"
    )

    __table_args__ = (
        Index("idx_tool_providers_type", "provider_type"),
    )


class LLMProvider(Base):
    """LLM provider registration (e.g. Ollama, OpenAI-compatible endpoints)."""

    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="'ollama', 'openai_compatible'"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Display name, e.g. 'Ollama (local)'"
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(
        String(500), comment="API key for OpenAI-compatible providers"
    )
    default_model: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Default model name, e.g. 'mistral:7b'. Null = set per workflow."
    )
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="Provider-specific additional configuration"
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
    workflows: Mapped[list["Workflow"]] = relationship(
        back_populates="llm_provider"
    )

    __table_args__ = (
        Index("idx_llm_providers_type", "provider_type"),
    )


class STTProvider(Base):
    """STT provider registration (e.g. Speaches, Whisper-ROCm, external Whisper APIs)."""

    __tablename__ = "stt_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="'whisper_openai_compatible'"
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Display name, e.g. 'Speaches (CPU)'"
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(
        String(500), comment="API key for authenticated providers"
    )
    default_model: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Default model name, e.g. 'Systran/faster-whisper-large-v3'"
    )
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="Provider-specific additional configuration"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="Default provider for /api/v1/transcribe (only one should be true)"
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
    workflows: Mapped[list["Workflow"]] = relationship(
        back_populates="stt_provider"
    )

    __table_args__ = (
        Index("idx_stt_providers_type", "provider_type"),
    )


class Workflow(Base):
    """Workflow definition model."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment="URL-friendly identifier"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(
        String(50), comment="e.g., 'text', 'voice', 'translation'"
    )

    # Execution
    execution_type: Mapped[str] = mapped_column(
        String(20), default="tool",
        comment="'pipeline', 'tool'"
    )

    # Tool provider delegation (when execution_type='tool')
    tool_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_providers.id", ondelete="SET NULL")
    )
    external_flow_id: Mapped[Optional[str]] = mapped_column(
        String(255), comment="Flow/workflow ID in the external tool"
    )
    input_mapping: Mapped[Optional[dict]] = mapped_column(
        JSONB, comment="Maps Ancroo input fields to tool input fields"
    )
    output_mapping: Mapped[Optional[dict]] = mapped_column(
        JSONB, comment="Maps tool output fields to Ancroo result fields"
    )
    sync_status: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual",
        comment="'synced', 'stale', 'missing', 'manual'"
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Pipeline (when execution_type='pipeline')
    pipeline_steps: Mapped[Optional[list]] = mapped_column(
        JSONB, default=list, server_default="[]",
        comment="Ordered list of pipeline step definitions"
    )

    # === New generic workflow system ===

    # Workflow type (UX category for admin GUI)
    workflow_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="'text_transformation', 'speech_to_text', 'workflow_trigger', 'custom'. null = legacy mode"
    )

    # Collection Recipe — sent to extension (public)
    recipe: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="What the extension should collect: {collect: [...], form_fields: [...]}"
    )

    # Target config — stays on server (private, contains internal URLs/keys)
    target_config: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="HTTP target: {url, method, headers, payload_template, response_mapping, timeout}"
    )

    # Output action — sent to extension (public)
    output_action: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="'replace_selection', 'clipboard', 'notification', 'fill_fields', 'none'"
    )

    # Configuration
    default_hotkey: Mapped[Optional[str]] = mapped_column(
        String(50), comment="e.g., 'ctrl+shift+g'"
    )
    input_type: Mapped[str] = mapped_column(
        String(50),
        default="clipboard",
        comment="'clipboard', 'text_selection', 'form'",
    )
    output_type: Mapped[str] = mapped_column(
        String(50),
        default="clipboard",
        comment="'clipboard', 'notification', 'window'",
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)

    # Metadata
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # LLM provider reference (for llm-backed workflows)
    llm_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_providers.id", ondelete="SET NULL"),
        comment="Assigned LLM provider (URL + credentials resolved at runtime)"
    )
    llm_model: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="Model override; falls back to provider.default_model if None"
    )

    # STT provider reference (for speech-to-text workflows)
    stt_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stt_providers.id", ondelete="SET NULL"),
        comment="Assigned STT provider (URL + model resolved at runtime)"
    )
    stt_model: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="Model override; falls back to provider.default_model if None"
    )

    # Relationships
    tool_provider: Mapped[Optional["ToolProvider"]] = relationship(
        back_populates="workflows"
    )
    llm_provider: Mapped[Optional["LLMProvider"]] = relationship(
        back_populates="workflows"
    )
    stt_provider: Mapped[Optional["STTProvider"]] = relationship(
        back_populates="workflows"
    )
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
        Index("idx_workflows_slug", "slug"),
        Index("idx_workflows_category", "category"),
        Index("idx_workflows_tool_provider", "tool_provider_id"),
        Index("idx_workflows_llm_provider", "llm_provider_id"),
        Index("idx_workflows_stt_provider", "stt_provider_id"),
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
