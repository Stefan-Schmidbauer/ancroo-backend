"""Add categories table and migrate workflow.category string to FK.

Revision ID: 016
Revises: 015
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Icon mapping matching the existing hardcoded values
CATEGORY_ICONS = {
    "text": "\u270F\uFE0F",
    "voice": "\uD83C\uDF99\uFE0F",
    "automation": "\u26A1",
    "translation": "\uD83C\uDF10",
    "code": "\uD83D\uDCBB",
}
DEFAULT_ICON = "\U0001f527"


def upgrade() -> None:
    # 1. Create categories table
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("icon", sa.String(10), nullable=False, server_default=DEFAULT_ICON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. Populate categories from existing distinct workflow.category values
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT DISTINCT category FROM workflows WHERE category IS NOT NULL")
    ).fetchall()

    for (cat_name,) in existing:
        icon = CATEGORY_ICONS.get(cat_name, DEFAULT_ICON)
        conn.execute(
            sa.text("INSERT INTO categories (id, name, icon) VALUES (gen_random_uuid(), :name, :icon)"),
            {"name": cat_name, "icon": icon},
        )

    # 3. Add category_id FK column to workflows
    op.add_column("workflows", sa.Column("category_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_workflows_category_id",
        "workflows",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4. Populate category_id from name matching
    conn.execute(
        sa.text("""
            UPDATE workflows w
            SET category_id = c.id
            FROM categories c
            WHERE w.category = c.name
        """)
    )

    # 5. Drop old column and index
    op.drop_index("idx_workflows_category", table_name="workflows")
    op.drop_column("workflows", "category")

    # 6. Create new index on category_id
    op.create_index("idx_workflows_category_id", "workflows", ["category_id"])


def downgrade() -> None:
    # 1. Re-add category string column
    op.add_column("workflows", sa.Column("category", sa.String(50), nullable=True))

    # 2. Populate from FK relationship
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE workflows w
            SET category = c.name
            FROM categories c
            WHERE w.category_id = c.id
        """)
    )

    # 3. Drop FK and column
    op.drop_index("idx_workflows_category_id", table_name="workflows")
    op.drop_constraint("fk_workflows_category_id", "workflows", type_="foreignkey")
    op.drop_column("workflows", "category_id")

    # 4. Recreate old index
    op.create_index("idx_workflows_category", "workflows", ["category"])

    # 5. Drop categories table
    op.drop_table("categories")
