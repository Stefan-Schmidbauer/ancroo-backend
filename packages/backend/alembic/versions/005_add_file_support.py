"""Add file upload metadata to execution_logs.

Revision ID: 005
Revises: 004
Create Date: 2026-02-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "execution_logs",
        sa.Column(
            "file_name", sa.String(255), nullable=True,
            comment="Original filename of uploaded file",
        ),
    )
    op.add_column(
        "execution_logs",
        sa.Column(
            "file_size_bytes", sa.Integer(), nullable=True,
            comment="Size of uploaded file in bytes",
        ),
    )


def downgrade() -> None:
    op.drop_column("execution_logs", "file_size_bytes")
    op.drop_column("execution_logs", "file_name")
