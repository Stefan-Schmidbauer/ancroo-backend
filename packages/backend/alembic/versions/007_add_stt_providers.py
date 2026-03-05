"""Add stt_providers table and STT provider fields to workflows.

Revision ID: 007
Revises: 006
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create stt_providers table
    op.create_table(
        "stt_providers",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "provider_type", sa.String(50), nullable=False,
            comment="'whisper_openai_compatible'",
        ),
        sa.Column(
            "name", sa.String(255), nullable=False,
            comment="Display name, e.g. 'Speaches (CPU)'",
        ),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column(
            "api_key", sa.String(500), nullable=True,
            comment="API key for authenticated providers",
        ),
        sa.Column(
            "default_model", sa.String(255), nullable=False,
            comment="Default model name, e.g. 'Systran/faster-whisper-large-v3'",
        ),
        sa.Column(
            "config", JSONB, server_default="{}",
            comment="Provider-specific additional configuration",
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column(
            "health_status", sa.String(20), server_default="unknown",
            comment="'healthy', 'unhealthy', 'unknown'",
        ),
        sa.Column("last_health_check", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index("idx_stt_providers_type", "stt_providers", ["provider_type"])

    # Extend workflows table with STT provider reference
    op.add_column(
        "workflows",
        sa.Column(
            "stt_provider_id", UUID(as_uuid=True), nullable=True,
            comment="Assigned STT provider (URL + model resolved at runtime)",
        ),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "stt_model", sa.String(255), nullable=True,
            comment="Model override; falls back to provider.default_model if None",
        ),
    )
    op.create_foreign_key(
        "fk_workflows_stt_provider",
        "workflows", "stt_providers",
        ["stt_provider_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_workflows_stt_provider", "workflows", ["stt_provider_id"])


def downgrade() -> None:
    op.drop_index("idx_workflows_stt_provider", table_name="workflows")
    op.drop_constraint("fk_workflows_stt_provider", "workflows", type_="foreignkey")
    op.drop_column("workflows", "stt_model")
    op.drop_column("workflows", "stt_provider_id")
    op.drop_index("idx_stt_providers_type", table_name="stt_providers")
    op.drop_table("stt_providers")
