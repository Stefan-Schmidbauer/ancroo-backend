"""Add endpoint_execute and endpoint_models columns to llm_models.

These columns store the API paths that were previously hardcoded in
the executor and health-check code.  Existing rows are back-filled
with the correct defaults based on their provider_type.

Revision ID: 019
Revises: 018
Create Date: 2026-03-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns with a temporary server default so existing rows get a value.
    op.add_column(
        "llm_models",
        sa.Column(
            "endpoint_execute",
            sa.String(255),
            nullable=False,
            server_default="/v1/chat/completions",
            comment="API path for execution, e.g. '/v1/chat/completions', '/v1/messages', '/api/generate'",
        ),
    )
    op.add_column(
        "llm_models",
        sa.Column(
            "endpoint_models",
            sa.String(255),
            nullable=False,
            server_default="/v1/models",
            comment="API path for model discovery/health, e.g. '/v1/models', '/api/tags'",
        ),
    )

    # Back-fill provider-specific defaults for existing rows.
    op.execute(
        "UPDATE llm_models SET endpoint_execute = '/api/generate', "
        "endpoint_models = '/api/tags' WHERE provider_type = 'ollama'"
    )
    op.execute(
        "UPDATE llm_models SET endpoint_execute = '/v1/messages' "
        "WHERE provider_type = 'anthropic'"
    )
    # All other providers already have the correct server_default values.

    # Drop the server defaults — the application layer handles defaults.
    op.alter_column("llm_models", "endpoint_execute", server_default=None)
    op.alter_column("llm_models", "endpoint_models", server_default=None)


def downgrade() -> None:
    op.drop_column("llm_models", "endpoint_models")
    op.drop_column("llm_models", "endpoint_execute")
