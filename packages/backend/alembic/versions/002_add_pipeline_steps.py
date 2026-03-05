"""Add pipeline_steps column to workflows.

Revision ID: 002
Revises: 001
Create Date: 2026-02-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("pipeline_steps", JSONB, server_default="[]", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflows", "pipeline_steps")
