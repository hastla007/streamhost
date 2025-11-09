"""Remove playlist position default value."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20240607_04"
down_revision = "20240605_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("playlist_entry") as batch:
        batch.alter_column("position", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("playlist_entry") as batch:
        batch.alter_column("position", server_default=sa.text("0"))
