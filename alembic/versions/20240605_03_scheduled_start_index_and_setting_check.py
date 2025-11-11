"""Add scheduled_start index and settings singleton constraint

Revision ID: 20240605_03
Revises: 20240601_02
Create Date: 2024-06-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20240605_03"
down_revision = "20240601_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_playlist_entry_scheduled_start",
        "playlist_entry",
        ["scheduled_start"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_system_setting_singleton",
        "system_setting",
        "id = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_system_setting_singleton", "system_setting", type_="check")
    op.drop_index("ix_playlist_entry_scheduled_start", table_name="playlist_entry")
