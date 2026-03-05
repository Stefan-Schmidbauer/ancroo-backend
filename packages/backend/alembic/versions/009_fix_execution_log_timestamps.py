"""Make all timestamp columns timezone-aware.

Fixes asyncpg DataError when inserting timezone-aware Python datetimes
into TIMESTAMP WITHOUT TIME ZONE columns.

Revision ID: 009
Revises: 008
Create Date: 2026-02-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All (table, column) pairs that need TIMESTAMP WITH TIME ZONE
_COLUMNS = [
    ("users", "created_at"),
    ("users", "updated_at"),
    ("users", "last_login_at"),
    ("workflows", "created_at"),
    ("workflows", "updated_at"),
    ("workflows", "last_synced_at"),
    ("workflow_permissions", "created_at"),
    ("tool_providers", "created_at"),
    ("tool_providers", "updated_at"),
    ("tool_providers", "last_health_check"),
    ("llm_providers", "created_at"),
    ("llm_providers", "updated_at"),
    ("llm_providers", "last_health_check"),
    ("stt_providers", "created_at"),
    ("stt_providers", "updated_at"),
    ("stt_providers", "last_health_check"),
    ("execution_logs", "started_at"),
    ("execution_logs", "completed_at"),
    ("user_hotkey_settings", "created_at"),
    ("user_hotkey_settings", "updated_at"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
        )
