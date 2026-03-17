"""Three-Area Refactor: Replace provider tables with LLM Models, STT Models, Tools.

Drop old provider tables and workflows. Recreate workflows with new schema
referencing llm_models, stt_models, tools tables.

All existing data is test data — no migration needed, just rebuild.

Revision ID: 015
Revises: 014
Create Date: 2026-03-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Drop everything that references old tables (test data only) ---

    # Tables with FK to workflows
    op.execute("DELETE FROM user_hotkey_settings")
    op.execute("DELETE FROM workflow_permissions")
    op.execute("DELETE FROM execution_logs")

    # Drop old tables entirely
    op.drop_table("user_hotkey_settings")
    op.drop_table("workflow_permissions")
    op.drop_table("execution_logs")
    op.drop_table("workflows")
    op.drop_table("llm_providers")
    op.drop_table("stt_providers")
    op.drop_table("tool_providers")

    # --- 2. Create new tables ---

    op.create_table(
        "llm_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider_type", sa.String(50), nullable=False, comment="'ollama', 'openai_compatible'"),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.String(500), nullable=True),
        sa.Column("model_id", sa.String(255), nullable=False, comment="e.g. 'mistral:7b'"),
        sa.Column("default_temperature", sa.Float, server_default="0.3"),
        sa.Column("config", postgresql.JSONB, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("health_status", sa.String(20), server_default="'unknown'"),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_llm_models_active", "llm_models", ["is_active"], postgresql_where=sa.text("is_active = true"))

    op.create_table(
        "stt_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider_type", sa.String(50), nullable=False, comment="'whisper_openai_compatible'"),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.String(500), nullable=True),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("default_language", sa.String(10), nullable=True, comment="ISO 639-1, null = auto-detect"),
        sa.Column("config", postgresql.JSONB, server_default="{}"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("is_default", sa.Boolean, server_default="false"),
        sa.Column("health_status", sa.String(20), server_default="'unknown'"),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_stt_models_active", "stt_models", ["is_active"], postgresql_where=sa.text("is_active = true"))

    op.create_table(
        "tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tool_type", sa.String(50), nullable=False, comment="'ar_plugin', 'n8n_webhook', 'custom_api'"),
        sa.Column("endpoint_url", sa.String(500), nullable=False),
        sa.Column("http_method", sa.String(10), server_default="'POST'"),
        sa.Column("headers", postgresql.JSONB, server_default="{}"),
        sa.Column("payload_template", sa.Text, nullable=True),
        sa.Column("response_mapping", sa.String(255), nullable=True),
        sa.Column("timeout", sa.Integer, server_default="120"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("input_schema", postgresql.JSONB, nullable=True),
        sa.Column("output_schema", postgresql.JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("health_status", sa.String(20), server_default="'unknown'"),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(50), nullable=True, comment="'auto_discovered', 'manual', 'imported'"),
        sa.Column("source_id", sa.String(255), nullable=True),
        sa.Column("n8n_base_url", sa.String(500), nullable=True),
        sa.Column("n8n_api_key", sa.String(500), nullable=True),
        sa.Column("n8n_flow_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_tools_type", "tools", ["tool_type"])
    op.create_index("idx_tools_active", "tools", ["is_active"], postgresql_where=sa.text("is_active = true"))
    op.create_index("idx_tools_source", "tools", ["source", "source_id"])

    # --- 3. Recreate workflows with new schema ---

    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        # Workflow type
        sa.Column("workflow_type", sa.String(30), nullable=False),
        # Execution target FKs (at most one)
        sa.Column("llm_model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt_template", sa.Text, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("stt_model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stt_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tools.id", ondelete="SET NULL"), nullable=True),
        # Collection & Output
        sa.Column("recipe", postgresql.JSONB, nullable=True),
        sa.Column("output_action", sa.String(30), nullable=True),
        # Configuration
        sa.Column("default_hotkey", sa.String(50), nullable=True),
        sa.Column("timeout_seconds", sa.Integer, server_default="60"),
        sa.Column("demo_url", sa.String(255), nullable=True),
        # Metadata
        sa.Column("version", sa.String(20), server_default="'1.0.0'"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # Constraints
        sa.CheckConstraint("num_nonnulls(llm_model_id, stt_model_id, tool_id) <= 1", name="check_single_execution_target"),
    )
    op.create_index("idx_workflows_slug", "workflows", ["slug"])
    op.create_index("idx_workflows_category", "workflows", ["category"])
    op.create_index("idx_workflows_llm_model", "workflows", ["llm_model_id"])
    op.create_index("idx_workflows_stt_model", "workflows", ["stt_model_id"])
    op.create_index("idx_workflows_tool", "workflows", ["tool_id"])
    op.create_index("idx_workflows_active", "workflows", ["is_active"], postgresql_where=sa.text("is_active = true"))

    # --- 4. Recreate dependent tables ---

    op.create_table(
        "workflow_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("group_name", sa.String(100), nullable=True),
        sa.Column("permission_level", sa.String(20), server_default="'execute'"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND group_name IS NULL) OR (user_id IS NULL AND group_name IS NOT NULL)",
            name="check_permission_target",
        ),
    )
    op.create_index("idx_workflow_permissions_workflow", "workflow_permissions", ["workflow_id"])
    op.create_index("idx_workflow_permissions_user", "workflow_permissions", ["user_id"])
    op.create_index("idx_workflow_permissions_group", "workflow_permissions", ["group_name"])

    op.create_table(
        "execution_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_preview", sa.Text, nullable=True),
        sa.Column("output_preview", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("client_version", sa.String(20), nullable=True),
        sa.Column("client_platform", sa.String(50), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
    )
    op.create_index("idx_execution_logs_user", "execution_logs", ["user_id"])
    op.create_index("idx_execution_logs_workflow", "execution_logs", ["workflow_id"])
    op.create_index("idx_execution_logs_started_at", "execution_logs", ["started_at"])
    op.create_index("idx_execution_logs_workflow_started", "execution_logs", ["workflow_id", "started_at"])

    op.create_table(
        "user_hotkey_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("custom_hotkey", sa.String(50), nullable=True),
        sa.Column("is_enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "workflow_id"),
    )


def downgrade() -> None:
    # Destructive — cannot restore data, only recreates old schema structure.
    # Not implementing full downgrade for a test-data-only migration.
    raise NotImplementedError(
        "Downgrade not supported for this migration. "
        "Restore from backup if needed."
    )
