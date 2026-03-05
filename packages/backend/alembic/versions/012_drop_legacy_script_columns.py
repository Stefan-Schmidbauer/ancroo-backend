"""Drop legacy script and webhook columns.

These columns are no longer used:
- client_script_path: was for filesystem-based client scripts (removed)
- server_script_path: was for filesystem-based server scripts (removed)
- activepieces_webhook_url: replaced by target_config in generic workflow system

Revision ID: 012
Revises: 011
Create Date: 2026-03-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("workflows", "client_script_path")
    op.drop_column("workflows", "server_script_path")
    op.drop_column("workflows", "activepieces_webhook_url")


def downgrade() -> None:
    op.add_column("workflows", sa.Column("activepieces_webhook_url", sa.String(500)))
    op.add_column("workflows", sa.Column("server_script_path", sa.String(500)))
    op.add_column("workflows", sa.Column("client_script_path", sa.String(500)))
