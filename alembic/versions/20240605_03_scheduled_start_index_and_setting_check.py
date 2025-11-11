"""Add scheduled_start index and settings singleton constraint

Revision ID: 20240605_03
Revises: 20240601_02
Create Date: 2024-06-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


INDEX_NAME = "ix_playlist_entry_scheduled_start"
CONSTRAINT_NAME = "ck_system_setting_singleton"


# revision identifiers, used by Alembic.
revision = "20240605_03"
down_revision = "20240601_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_indexes = {index["name"] for index in inspector.get_indexes("playlist_entry")}
    if INDEX_NAME not in existing_indexes:
        op.create_index(
            INDEX_NAME,
            "playlist_entry",
            ["scheduled_start"],
            unique=False,
        )

    if bind.dialect.name == "sqlite":
        # SQLite cannot ALTER tables to add constraints without a full table rebuild.
        # The database still enforces the singleton invariant at the application layer.
        return

    existing_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("system_setting")
    }
    if CONSTRAINT_NAME not in existing_checks:
        op.create_check_constraint(
            CONSTRAINT_NAME,
            "system_setting",
            "id = 1",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        inspector = sa.inspect(bind)
        existing_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("system_setting")
        }
        if CONSTRAINT_NAME in existing_checks:
            op.drop_constraint(CONSTRAINT_NAME, "system_setting", type_="check")

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("playlist_entry")}
    if INDEX_NAME in existing_indexes:
        op.drop_index(INDEX_NAME, table_name="playlist_entry")
