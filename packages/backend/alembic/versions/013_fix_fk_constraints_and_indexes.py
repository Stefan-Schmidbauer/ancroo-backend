"""Fix FK constraints and add indexes.

- workflows.created_by: add ON DELETE SET NULL
- execution_logs.workflow_id: add ON DELETE SET NULL
- execution_logs.user_id: add ON DELETE SET NULL
- Add partial index on workflows.is_active (WHERE true)
- Add composite index on execution_logs (workflow_id, started_at)

Revision ID: 013
Revises: 012
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix workflows.created_by FK: add ON DELETE SET NULL
    op.drop_constraint(
        "workflows_created_by_fkey", "workflows", type_="foreignkey"
    )
    op.create_foreign_key(
        "workflows_created_by_fkey",
        "workflows",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # Fix execution_logs.workflow_id FK: add ON DELETE SET NULL
    op.drop_constraint(
        "execution_logs_workflow_id_fkey", "execution_logs", type_="foreignkey"
    )
    op.create_foreign_key(
        "execution_logs_workflow_id_fkey",
        "execution_logs",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Fix execution_logs.user_id FK: add ON DELETE SET NULL
    op.drop_constraint(
        "execution_logs_user_id_fkey", "execution_logs", type_="foreignkey"
    )
    op.create_foreign_key(
        "execution_logs_user_id_fkey",
        "execution_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Partial index: only active workflows (common filter)
    op.create_index(
        "idx_workflows_active",
        "workflows",
        ["is_active"],
        postgresql_where="is_active = true",
    )

    # Composite index: workflow execution history queries
    op.create_index(
        "idx_execution_logs_workflow_started",
        "execution_logs",
        ["workflow_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_execution_logs_workflow_started", table_name="execution_logs")
    op.drop_index("idx_workflows_active", table_name="workflows")

    # Restore execution_logs.user_id FK without ON DELETE
    op.drop_constraint(
        "execution_logs_user_id_fkey", "execution_logs", type_="foreignkey"
    )
    op.create_foreign_key(
        "execution_logs_user_id_fkey",
        "execution_logs",
        "users",
        ["user_id"],
        ["id"],
    )

    # Restore execution_logs.workflow_id FK without ON DELETE
    op.drop_constraint(
        "execution_logs_workflow_id_fkey", "execution_logs", type_="foreignkey"
    )
    op.create_foreign_key(
        "execution_logs_workflow_id_fkey",
        "execution_logs",
        "workflows",
        ["workflow_id"],
        ["id"],
    )

    # Restore workflows.created_by FK without ON DELETE
    op.drop_constraint(
        "workflows_created_by_fkey", "workflows", type_="foreignkey"
    )
    op.create_foreign_key(
        "workflows_created_by_fkey",
        "workflows",
        "users",
        ["created_by"],
        ["id"],
    )
