"""subject profile fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25 13:07:20.864666
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEX = postgresql.ENUM("female", "male", "other", name="sex", create_type=False)


def upgrade() -> None:
    # add_column doesn't create PostgreSQL enum types: create it explicitly first.
    postgresql.ENUM("female", "male", "other", name="sex").create(op.get_bind(), checkfirst=True)
    op.add_column("users", sa.Column("sex", SEX, nullable=True))
    op.add_column("users", sa.Column("height_cm", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("weight_kg", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("hr_rest", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "height_range", "users", "height_cm IS NULL OR height_cm BETWEEN 80 AND 250"
    )
    op.create_check_constraint(
        "weight_range", "users", "weight_kg IS NULL OR weight_kg BETWEEN 20 AND 300"
    )
    op.create_check_constraint(
        "hr_rest_range", "users", "hr_rest IS NULL OR hr_rest BETWEEN 25 AND 120"
    )


def downgrade() -> None:
    for name in ("hr_rest_range", "weight_range", "height_range"):
        op.drop_constraint(op.f(f"ck_users_{name}"), "users", type_="check")
    op.drop_column("users", "hr_rest")
    op.drop_column("users", "weight_kg")
    op.drop_column("users", "height_cm")
    op.drop_column("users", "sex")
    sa.Enum(name="sex").drop(op.get_bind(), checkfirst=True)
