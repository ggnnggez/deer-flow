"""Keep incomplete Ansich context snapshots queryable and repairable.

Revision ID: 0008_ansich_context_resilience
Revises: 0007_ansich_steps_and_context
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0008_ansich_context_resilience"
down_revision: str | Sequence[str] | None = "0007_ansich_steps_and_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    safe_add_column(
        "ansich_context_snapshots",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="complete"),
    )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ansich_context_snapshot_missing_items"):
        op.create_table(
            "ansich_context_snapshot_missing_items",
            sa.Column("snapshot_id", sa.String(length=36), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("expected_content_block_id", sa.String(length=36), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=True),
            sa.Column("name", sa.String(length=256), nullable=True),
            sa.Column("message_id", sa.String(length=256), nullable=True),
            sa.Column("visible_bytes", sa.BigInteger(), nullable=False),
            sa.Column("estimated_tokens", sa.BigInteger(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["snapshot_id"], ["ansich_context_snapshots.entity_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("snapshot_id", "ordinal"),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("ansich_context_snapshot_missing_items")}
    if "ix_ansich_context_snapshot_missing_items_block" not in indexes:
        op.create_index(
            "ix_ansich_context_snapshot_missing_items_block",
            "ansich_context_snapshot_missing_items",
            ["expected_content_block_id"],
            unique=False,
        )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ansich_context_snapshot_missing_items"):
        op.drop_table("ansich_context_snapshot_missing_items")
    safe_drop_column("ansich_context_snapshots", "status")
