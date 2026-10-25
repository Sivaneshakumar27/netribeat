"""sessions, files, analysis results

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 11:01:10.038710
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "type",
            sa.Enum("rest", "training", "match", "recovery", "test", name="session_type"),
            nullable=False,
        ),
        sa.Column(
            "device",
            sa.Enum(
                "chest_strap_rr_acc",
                "chest_strap_rr",
                "ecg_holter",
                "optical_wrist",
                "other",
                name="device",
            ),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at_source",
            sa.Enum("form", "file", "upload_time", "unknown", name="value_source"),
            nullable=False,
        ),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column(
            "age_source",
            sa.Enum("form", "file", "upload_time", "unknown", name="value_source"),
            nullable=False,
        ),
        sa.Column("hr_max_manual", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("processing", "ready", "failed", name="session_status"),
            nullable=False,
        ),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality", sa.String(length=16), nullable=True),
        sa.Column("reliable", sa.Boolean(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("avg_hr", sa.Float(), nullable=True),
        sa.Column("max_hr", sa.Float(), nullable=True),
        sa.Column("rmssd", sa.Float(), nullable=True),
        sa.Column("training_load", sa.Float(), nullable=True),
        sa.Column("artefact_count", sa.Integer(), nullable=True),
        sa.Column("artefact_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "age IS NULL OR age BETWEEN 8 AND 100", name=op.f("ck_sessions_age_range")
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_sessions_attempts_nonneg")),
        sa.CheckConstraint(
            "hr_max_manual IS NULL OR hr_max_manual BETWEEN 100 AND 230",
            name=op.f("ck_sessions_hr_max_range"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_sessions_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
    )
    op.create_index("ix_sessions_recorded_at", "sessions", ["recorded_at"], unique=False)
    op.create_index("ix_sessions_status", "sessions", ["status"], unique=False)
    op.create_index(
        "ix_sessions_user_recorded", "sessions", ["user_id", "recorded_at"], unique=False
    )
    op.create_table(
        "analysis_results",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_version", sa.String(length=20), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_analysis_results_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_analysis_results")),
    )
    op.create_table(
        "session_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=True),
        sa.Column("format", sa.String(length=40), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_session_files_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_files")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_session_files_storage_key")),
    )
    op.create_index("ix_session_files_session_id", "session_files", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_session_files_session_id", table_name="session_files")
    op.drop_table("session_files")
    op.drop_table("analysis_results")
    op.drop_index("ix_sessions_user_recorded", table_name="sessions")
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_index("ix_sessions_recorded_at", table_name="sessions")
    op.drop_table("sessions")
    bind = op.get_bind()
    for enum_name in ("session_type", "device", "value_source", "session_status"):
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)
