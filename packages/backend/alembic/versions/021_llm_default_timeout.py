"""Move primary timeout default from workflow to LLM model.

Cold-load + token-generation speed are model+hardware properties, so
the natural place for the default timeout is the LLM model. Workflows
keep an optional override for cases that need a tighter or looser bound.

Revision ID: 021
Revises: 020
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New per-model default. 120s is a comfortable headroom for 32B
    # local models with thinking, while staying responsive for 7B.
    op.add_column(
        "llm_models",
        sa.Column(
            "default_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
            comment="Default request timeout in seconds. Workflows can override.",
        ),
    )
    op.alter_column("llm_models", "default_timeout_seconds", server_default=None)

    # Workflow timeout becomes optional — NULL means "use model default".
    op.alter_column(
        "workflows",
        "timeout_seconds",
        nullable=True,
        server_default=None,
        existing_type=sa.Integer(),
    )


def downgrade() -> None:
    op.alter_column(
        "workflows",
        "timeout_seconds",
        nullable=False,
        server_default="60",
        existing_type=sa.Integer(),
    )
    op.execute("UPDATE workflows SET timeout_seconds = 60 WHERE timeout_seconds IS NULL")
    op.drop_column("llm_models", "default_timeout_seconds")
