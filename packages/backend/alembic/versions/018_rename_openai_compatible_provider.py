"""Rename LLM provider_type 'openai_compatible' to 'custom_openai'.

Part of the LLM provider registry expansion — 'openai_compatible' is
replaced by specific providers (openai, anthropic, openrouter, etc.)
with 'custom_openai' as the catch-all for generic OpenAI-compatible
endpoints.

Revision ID: 018
Revises: 017
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE llm_models SET provider_type = 'custom_openai' "
        "WHERE provider_type = 'openai_compatible'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE llm_models SET provider_type = 'openai_compatible' "
        "WHERE provider_type = 'custom_openai'"
    )
