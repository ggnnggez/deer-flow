"""Store reusable immutable Ansich ContextStates and ordered deltas.

Revision ID: 0011_ansich_context_states
Revises: 0010_ansich_content_occurrences
Create Date: 2026-07-17
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0011_ansich_context_states"
down_revision: str | Sequence[str] | None = "0010_ansich_content_occurrences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTEXT_STATE_NAMESPACE = "a63fb270-277c-5f30-83ad-37b338b53d68"


def _deterministic_uuid4(value: str) -> str:
    digest = hashlib.sha256(f"{_CONTEXT_STATE_NAMESPACE}:{value}".encode()).digest()
    return str(UUID(bytes=digest[:16], version=4))


def _state_hash(items: list[dict]) -> str:
    encoded = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _backfill_context_states() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    entities = sa.Table("ansich_entities", metadata, autoload_with=bind)
    observations = sa.Table("ansich_observations", metadata, autoload_with=bind)
    blocks = sa.Table("ansich_content_blocks", metadata, autoload_with=bind)
    snapshots = sa.Table("ansich_context_snapshots", metadata, autoload_with=bind)
    snapshot_items = sa.Table("ansich_context_snapshot_items", metadata, autoload_with=bind)
    missing_items = sa.Table("ansich_context_snapshot_missing_items", metadata, autoload_with=bind)
    states = sa.Table("ansich_context_states", metadata, autoload_with=bind)
    checkpoint_items = sa.Table("ansich_context_state_checkpoint_items", metadata, autoload_with=bind)
    state_missing = sa.Table("ansich_context_state_missing_blocks", metadata, autoload_with=bind)
    available_blocks = set(bind.execute(sa.select(blocks.c.entity_id)).scalars())

    snapshot_rows = bind.execute(sa.select(snapshots).order_by(snapshots.c.request_obs_id)).mappings().all()
    for snapshot in snapshot_rows:
        complete = bind.execute(sa.select(snapshot_items).where(snapshot_items.c.snapshot_id == snapshot["entity_id"]).order_by(snapshot_items.c.ordinal)).mappings()
        missing = bind.execute(sa.select(missing_items).where(missing_items.c.snapshot_id == snapshot["entity_id"]).order_by(missing_items.c.ordinal)).mappings()
        item_by_ordinal: dict[int, dict] = {}
        for item in complete:
            item_by_ordinal[int(item["ordinal"])] = {
                "ordinal": int(item["ordinal"]),
                "channel": item["channel"],
                "role": item["role"],
                "message_id": item["message_id"],
                "source_identity": item["source_identity"],
                "name": item["name"],
                "block_id": item["content_block_id"],
                "visible_bytes": int(item["visible_bytes"]),
                "estimated_tokens": int(item["estimated_tokens"]),
                "metadata": dict(item["metadata_json"] or {}),
            }
        for item in missing:
            item_by_ordinal[int(item["ordinal"])] = {
                "ordinal": int(item["ordinal"]),
                "channel": item["channel"],
                "role": item["role"],
                "message_id": item["message_id"],
                "source_identity": item["source_identity"],
                "name": item["name"],
                "block_id": item["expected_content_block_id"],
                "visible_bytes": int(item["visible_bytes"]),
                "estimated_tokens": int(item["estimated_tokens"]),
                "metadata": dict(item["metadata_json"] or {}),
            }
        items = [item_by_ordinal[ordinal] for ordinal in sorted(item_by_ordinal)]
        if [item["ordinal"] for item in items] != list(range(len(items))):
            continue
        state_hash = _state_hash(items)
        state_id = _deterministic_uuid4(f"context-state:{snapshot['task_id']}:{state_hash}")
        existing = bind.execute(sa.select(states.c.state_id).where(states.c.state_id == state_id)).scalar_one_or_none()
        if existing is None:
            state_observation = bind.execute(
                sa.select(observations.c.obs_id, observations.c.recorded_at)
                .where(
                    observations.c.kind == "context.snapshotted",
                    observations.c.subject_id == snapshot["entity_id"],
                )
                .order_by(observations.c.ingest_seq)
                .limit(1)
            ).first()
            if state_observation is None:
                continue
            if bind.execute(sa.select(entities.c.entity_id).where(entities.c.entity_id == state_id)).scalar_one_or_none() is None:
                bind.execute(
                    sa.insert(entities).values(
                        entity_id=state_id,
                        entity_type="context_state",
                        discovered_obs_id=state_observation.obs_id,
                    )
                )
            missing_block_ids = sorted({item["block_id"] for item in items} - available_blocks)
            bind.execute(
                sa.insert(states).values(
                    state_id=state_id,
                    task_id=snapshot["task_id"],
                    state_hash=state_hash,
                    parent_state_id=None,
                    created_obs_id=state_observation.obs_id,
                    chain_depth=0,
                    item_count=len(items),
                    is_checkpoint=True,
                    status="incomplete" if missing_block_ids else "complete",
                    created_at=state_observation.recorded_at,
                )
            )
            for item in items:
                bind.execute(
                    sa.insert(checkpoint_items).values(
                        state_id=state_id,
                        ordinal=item["ordinal"],
                        channel=item["channel"],
                        role=item["role"],
                        message_id=item["message_id"],
                        source_identity=item["source_identity"],
                        name=item["name"],
                        block_id=item["block_id"],
                        visible_bytes=item["visible_bytes"],
                        estimated_tokens=item["estimated_tokens"],
                        metadata_json=item["metadata"],
                    )
                )
            for block_id in missing_block_ids:
                bind.execute(sa.insert(state_missing).values(state_id=state_id, block_id=block_id))
        bind.execute(sa.update(snapshots).where(snapshots.c.entity_id == snapshot["entity_id"]).values(state_id=state_id))


def upgrade() -> None:
    safe_add_column(
        "ansich_content_blobs",
        sa.Column("payload_status", sa.String(length=16), nullable=False, server_default="available"),
    )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ansich_context_states"):
        op.create_table(
            "ansich_context_states",
            sa.Column("state_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("state_hash", sa.String(length=64), nullable=True),
            sa.Column("parent_state_id", sa.String(length=36), nullable=True),
            sa.Column("created_obs_id", sa.String(length=36), nullable=True),
            sa.Column("chain_depth", sa.Integer(), nullable=False),
            sa.Column("item_count", sa.Integer(), nullable=False),
            sa.Column("is_checkpoint", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["created_obs_id"], ["ansich_observations.obs_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["parent_state_id"], ["ansich_context_states.state_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["state_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["task_id"], ["ansich_tasks.entity_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("state_id"),
            sa.UniqueConstraint("created_obs_id"),
            sa.UniqueConstraint("task_id", "state_hash", name="uq_ansich_context_state_task_hash"),
        )
        op.create_index("ix_ansich_context_states_task_created", "ansich_context_states", ["task_id", "created_at"])
        op.create_index("ix_ansich_context_states_parent", "ansich_context_states", ["parent_state_id"])
    if not sa.inspect(op.get_bind()).has_table("ansich_context_state_checkpoint_items"):
        op.create_table(
            "ansich_context_state_checkpoint_items",
            sa.Column("state_id", sa.String(length=36), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=True),
            sa.Column("message_id", sa.String(length=256), nullable=True),
            sa.Column("source_identity", sa.String(length=512), nullable=True),
            sa.Column("name", sa.String(length=256), nullable=True),
            sa.Column("block_id", sa.String(length=36), nullable=False),
            sa.Column("visible_bytes", sa.BigInteger(), nullable=False),
            sa.Column("estimated_tokens", sa.BigInteger(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["state_id"], ["ansich_context_states.state_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("state_id", "ordinal"),
        )
        op.create_index(
            "ix_ansich_context_state_checkpoint_items_block",
            "ansich_context_state_checkpoint_items",
            ["block_id"],
        )
    if not sa.inspect(op.get_bind()).has_table("ansich_context_state_deltas"):
        op.create_table(
            "ansich_context_state_deltas",
            sa.Column("state_id", sa.String(length=36), nullable=False),
            sa.Column("operation_ordinal", sa.Integer(), nullable=False),
            sa.Column("operation", sa.String(length=16), nullable=False),
            sa.Column("source_ordinal", sa.Integer(), nullable=True),
            sa.Column("target_ordinal", sa.Integer(), nullable=True),
            sa.Column("channel", sa.String(length=32), nullable=True),
            sa.Column("role", sa.String(length=16), nullable=True),
            sa.Column("message_id", sa.String(length=256), nullable=True),
            sa.Column("source_identity", sa.String(length=512), nullable=True),
            sa.Column("name", sa.String(length=256), nullable=True),
            sa.Column("block_id", sa.String(length=36), nullable=True),
            sa.Column("visible_bytes", sa.BigInteger(), nullable=True),
            sa.Column("estimated_tokens", sa.BigInteger(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["state_id"], ["ansich_context_states.state_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("state_id", "operation_ordinal"),
        )
        op.create_index("ix_ansich_context_state_deltas_block", "ansich_context_state_deltas", ["block_id"])
    if not sa.inspect(op.get_bind()).has_table("ansich_context_state_missing_blocks"):
        op.create_table(
            "ansich_context_state_missing_blocks",
            sa.Column("state_id", sa.String(length=36), nullable=False),
            sa.Column("block_id", sa.String(length=36), nullable=False),
            sa.ForeignKeyConstraint(["state_id"], ["ansich_context_states.state_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("state_id", "block_id"),
        )
        op.create_index(
            "ix_ansich_context_state_missing_blocks_block",
            "ansich_context_state_missing_blocks",
            ["block_id"],
        )
    safe_add_column(
        "ansich_context_snapshots",
        sa.Column(
            "state_id",
            sa.String(length=36),
            sa.ForeignKey("ansich_context_states.state_id", ondelete="RESTRICT", name="fk_ansich_context_snapshots_state_id"),
            nullable=True,
        ),
    )
    _backfill_context_states()


def downgrade() -> None:
    safe_drop_column("ansich_context_snapshots", "state_id")
    for table in (
        "ansich_context_state_missing_blocks",
        "ansich_context_state_deltas",
        "ansich_context_state_checkpoint_items",
        "ansich_context_states",
    ):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
    safe_drop_column("ansich_content_blobs", "payload_status")
