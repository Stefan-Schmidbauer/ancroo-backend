"""Add context_length column to llm_models.

Lets admins pin num_ctx for Ollama models so the runtime KV cache stays
sized to the workflow's needs rather than the GGUF max (which can be
orders of magnitude larger and cause OOM/timeouts on first load).

Revision ID: 020
Revises: 019
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column(
            "context_length",
            sa.Integer(),
            nullable=True,
            comment="Override num_ctx for Ollama. NULL = let provider decide.",
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_models", "context_length")
