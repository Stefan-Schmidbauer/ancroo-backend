"""Add default_language column to stt_providers table.

Allows configuring a default language (ISO 639-1) per STT provider so
Whisper transcribes in the correct language instead of auto-detecting
(which can cause translation instead of transcription).

Revision ID: 014
Revises: 013
Create Date: 2026-03-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stt_providers",
        sa.Column(
            "default_language",
            sa.String(10),
            nullable=True,
            comment="Default ISO 639-1 language code (e.g. 'de', 'en'). Null = auto-detect.",
        ),
    )


def downgrade() -> None:
    op.drop_column("stt_providers", "default_language")
