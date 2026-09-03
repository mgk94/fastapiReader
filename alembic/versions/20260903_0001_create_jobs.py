"""Create the PostgreSQL-backed jobs queue and result store.

Revision ID: 20260903_0001
Revises:
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260903_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

job_status = postgresql.ENUM(
    "queued", "processing", "done", "failed", name="job_status", create_type=False
)


def upgrade() -> None:
    job_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("district_id", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("status", job_status, server_default="queued", nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_batch_id", "jobs", ["batch_id"])
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_index("ix_jobs_batch_id", table_name="jobs")
    op.drop_table("jobs")
    job_status.drop(op.get_bind(), checkfirst=True)
