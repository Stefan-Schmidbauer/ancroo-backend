"""Add tool_providers table and extend workflows for tool delegation.

Revision ID: 003
Revises: 002
Create Date: 2026-02-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tool_providers table
    op.create_table(
        "tool_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("provider_type", sa.String(50), nullable=False, comment="'n8n', 'custom_api', etc."),
        sa.Column("name", sa.String(255), nullable=False, comment="Display name"),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.String(500), nullable=True, comment="API key for authentication"),
        sa.Column("config", JSONB, server_default="{}", comment="Provider-specific additional configuration"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("health_status", sa.String(20), server_default="unknown", comment="'healthy', 'unhealthy', 'unknown'"),
        sa.Column("last_health_check", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index("idx_tool_providers_type", "tool_providers", ["provider_type"])

    # Extend workflows table for tool delegation
    op.add_column("workflows", sa.Column("tool_provider_id", UUID(as_uuid=True), nullable=True))
    op.add_column("workflows", sa.Column("external_flow_id", sa.String(255), nullable=True, comment="Flow/workflow ID in the external tool"))
    op.add_column("workflows", sa.Column("input_mapping", JSONB, nullable=True, comment="Maps Ancroo input fields to tool input fields"))
    op.add_column("workflows", sa.Column("output_mapping", JSONB, nullable=True, comment="Maps tool output fields to Ancroo result fields"))
    op.add_column("workflows", sa.Column("sync_status", sa.String(20), server_default="manual", comment="'synced', 'stale', 'missing', 'manual'"))
    op.add_column("workflows", sa.Column("last_synced_at", sa.DateTime(), nullable=True))

    op.create_foreign_key(
        "fk_workflows_tool_provider",
        "workflows", "tool_providers",
        ["tool_provider_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_workflows_tool_provider", "workflows", ["tool_provider_id"])


def downgrade() -> None:
    op.drop_index("idx_workflows_tool_provider", table_name="workflows")
    op.drop_constraint("fk_workflows_tool_provider", "workflows", type_="foreignkey")
    op.drop_column("workflows", "last_synced_at")
    op.drop_column("workflows", "sync_status")
    op.drop_column("workflows", "output_mapping")
    op.drop_column("workflows", "input_mapping")
    op.drop_column("workflows", "external_flow_id")
    op.drop_column("workflows", "tool_provider_id")
    op.drop_index("idx_tool_providers_type", table_name="tool_providers")
    op.drop_table("tool_providers")
