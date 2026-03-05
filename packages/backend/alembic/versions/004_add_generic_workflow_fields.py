"""Add generic workflow fields: workflow_type, recipe, target_config, output_action.

Revision ID: 004
Revises: 003
Create Date: 2026-02-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "workflow_type", sa.String(30), nullable=True,
            comment="'text_transformation', 'workflow_trigger', 'custom'. null = legacy mode",
        ),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "recipe", JSONB, nullable=True,
            comment="Collection recipe: what the extension should collect",
        ),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "target_config", JSONB, nullable=True,
            comment="HTTP target config (private, stays on server)",
        ),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "output_action", sa.String(30), nullable=True,
            comment="'replace_selection', 'clipboard', 'notification', 'fill_fields', 'none'",
        ),
    )


def downgrade() -> None:
    op.drop_column("workflows", "output_action")
    op.drop_column("workflows", "target_config")
    op.drop_column("workflows", "recipe")
    op.drop_column("workflows", "workflow_type")
