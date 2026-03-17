"""Tighten workflow execution target constraint from <= 1 to exactly 1.

Every workflow must reference exactly one execution target (LLM model,
STT model, or tool).  The admin GUI already enforces this via required
selects — this migration aligns the DB constraint.

Revision ID: 017
Revises: 016
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("check_single_execution_target", "workflows")
    op.create_check_constraint(
        "check_single_execution_target",
        "workflows",
        "num_nonnulls(llm_model_id, stt_model_id, tool_id) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("check_single_execution_target", "workflows")
    op.create_check_constraint(
        "check_single_execution_target",
        "workflows",
        "num_nonnulls(llm_model_id, stt_model_id, tool_id) <= 1",
    )
