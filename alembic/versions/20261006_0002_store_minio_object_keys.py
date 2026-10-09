"""Store MinIO object keys instead of local file paths.

Revision ID: 20261006_0002
Revises: 20260903_0001
"""
from typing import Sequence

from alembic import op


revision: str = "20261006_0002"
down_revision: str | None = "20260903_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("jobs", "file_path", new_column_name="object_key")


def downgrade() -> None:
    op.alter_column("jobs", "object_key", new_column_name="file_path")
