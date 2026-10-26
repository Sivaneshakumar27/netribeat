"""rename users.sex to users.gender (and the enum type sex to gender)

Renames in place: values already saved (female / male / other) are kept.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE sex RENAME TO gender")
    op.alter_column("users", "sex", new_column_name="gender")


def downgrade() -> None:
    op.alter_column("users", "gender", new_column_name="sex")
    op.execute("ALTER TYPE gender RENAME TO sex")
