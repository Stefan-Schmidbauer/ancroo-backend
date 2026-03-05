"""Make default_model nullable on llm_providers.

Allows providers to be created without a default model — admins
can set the model per-workflow instead.

Revision ID: 011
Revises: 010
Create Date: 2026-03-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "llm_providers",
        "default_model",
        existing_type=sa.String(255),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE llm_providers SET default_model = 'UNSET' WHERE default_model IS NULL")
    op.alter_column(
        "llm_providers",
        "default_model",
        existing_type=sa.String(255),
        nullable=False,
    )
