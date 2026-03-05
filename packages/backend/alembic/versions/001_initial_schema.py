"""Initial schema.

Revision ID: 001
Revises:
Create Date: 2026-02-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), unique=True, nullable=False, comment="sub claim from OIDC provider"),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("groups", ARRAY(sa.String), server_default="{}"),
        sa.Column("is_admin", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime),
    )

    # Workflows
    op.create_table(
        "workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("category", sa.String(50)),
        sa.Column("execution_type", sa.String(20), server_default="script"),
        sa.Column("activepieces_webhook_url", sa.String(500)),
        sa.Column("client_script_path", sa.String(500)),
        sa.Column("server_script_path", sa.String(500)),
        sa.Column("default_hotkey", sa.String(50)),
        sa.Column("input_type", sa.String(50), server_default="clipboard"),
        sa.Column("output_type", sa.String(50), server_default="clipboard"),
        sa.Column("timeout_seconds", sa.Integer, server_default="60"),
        sa.Column("version", sa.String(20), server_default="1.0.0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("idx_workflows_slug", "workflows", ["slug"])
    op.create_index("idx_workflows_category", "workflows", ["category"])

    # Workflow permissions
    op.create_table(
        "workflow_permissions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("group_name", sa.String(100)),
        sa.Column("permission_level", sa.String(20), server_default="execute"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND group_name IS NULL) OR (user_id IS NULL AND group_name IS NOT NULL)",
            name="check_permission_target",
        ),
    )
    op.create_index("idx_workflow_permissions_workflow", "workflow_permissions", ["workflow_id"])
    op.create_index("idx_workflow_permissions_user", "workflow_permissions", ["user_id"])
    op.create_index("idx_workflow_permissions_group", "workflow_permissions", ["group_name"])

    # Execution logs
    op.create_table(
        "execution_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_preview", sa.Text),
        sa.Column("output_preview", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("client_version", sa.String(20)),
        sa.Column("client_platform", sa.String(50)),
    )
    op.create_index("idx_execution_logs_user", "execution_logs", ["user_id"])
    op.create_index("idx_execution_logs_workflow", "execution_logs", ["workflow_id"])
    op.create_index("idx_execution_logs_started_at", "execution_logs", ["started_at"])

    # User hotkey settings
    op.create_table(
        "user_hotkey_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("custom_hotkey", sa.String(50)),
        sa.Column("is_enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "workflow_id"),
    )

    # Secrets
    op.create_table(
        "secrets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("encrypted_value", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("secrets")
    op.drop_table("user_hotkey_settings")
    op.drop_table("execution_logs")
    op.drop_table("workflow_permissions")
    op.drop_table("workflows")
    op.drop_table("users")
