"""Add playlist position counter and enforce unique ordering"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20240601_02"
down_revision = "20240531_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playlist_position_counter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("value", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    counter_table = sa.table(
        "playlist_position_counter",
        sa.column("id", sa.Integer()),
        sa.column("value", sa.Integer()),
    )
    op.bulk_insert(counter_table, [{"id": 1, "value": 0}])

    op.drop_index("ix_playlist_entry_position", table_name="playlist_entry")
    op.create_index(
        "ix_playlist_entry_position",
        "playlist_entry",
        ["position"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_playlist_entry_position", table_name="playlist_entry")
    op.create_index(
        "ix_playlist_entry_position",
        "playlist_entry",
        ["position"],
        unique=False,
    )
    op.drop_table("playlist_position_counter")
