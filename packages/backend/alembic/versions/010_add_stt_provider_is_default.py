"""Add is_default column to stt_providers for explicit default provider selection.

Revision ID: 010
Revises: 009
Create Date: 2026-03-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stt_providers",
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.text("false"),
            comment="Default provider for /api/v1/transcribe (only one should be true)",
        ),
    )


def downgrade() -> None:
    op.drop_column("stt_providers", "is_default")
