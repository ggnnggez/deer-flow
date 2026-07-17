"""Add Ansich context compression and bidirectional lineage projections.

Revision ID: 0014_ansich_context_lineage
Revises: 0013_ansich_tool_accountability
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from ansich import ContextStateDelta, ContextStateItem
from ansich.context_state import materialize_context_state

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0014_ansich_context_lineage"
down_revision: str | Sequence[str] | None = "0013_ansich_tool_accountability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table_name) if index.get("name")}


def _backfill_block_producers() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not all(
        inspector.has_table(table)
        for table in (
            "ansich_block_producers",
            "ansich_content_blocks",
            "ansich_observations",
        )
    ):
        return
    metadata = sa.MetaData()
    producers = sa.Table("ansich_block_producers", metadata, autoload_with=bind)
    blocks = sa.Table("ansich_content_blocks", metadata, autoload_with=bind)
    observations = sa.Table("ansich_observations", metadata, autoload_with=bind)
    existing = set(bind.execute(sa.select(producers.c.block_id)).scalars())
    rows = bind.execute(
        sa.select(
            blocks.c.entity_id,
            blocks.c.producer_obs_id,
            observations.c.producer_name,
        ).join(
            observations,
            observations.c.obs_id == blocks.c.producer_obs_id,
        )
    )
    for row in rows:
        if row.entity_id in existing:
            continue
        bind.execute(
            sa.insert(producers).values(
                block_id=row.entity_id,
                producer_kind=row.producer_name,
                producer_entity_id=None,
                producer_obs_id=row.producer_obs_id,
            )
        )


def _backfill_snapshot_block_memberships() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    required = (
        "ansich_context_snapshot_block_memberships",
        "ansich_context_snapshots",
        "ansich_context_snapshot_items",
        "ansich_context_states",
        "ansich_context_state_checkpoint_items",
        "ansich_context_state_deltas",
        "ansich_content_blocks",
    )
    if not all(inspector.has_table(table) for table in required):
        return
    metadata = sa.MetaData()
    memberships = sa.Table(
        "ansich_context_snapshot_block_memberships",
        metadata,
        autoload_with=bind,
    )
    snapshots = sa.Table("ansich_context_snapshots", metadata, autoload_with=bind)
    snapshot_items = sa.Table("ansich_context_snapshot_items", metadata, autoload_with=bind)
    states = sa.Table("ansich_context_states", metadata, autoload_with=bind)
    checkpoints = sa.Table("ansich_context_state_checkpoint_items", metadata, autoload_with=bind)
    deltas = sa.Table("ansich_context_state_deltas", metadata, autoload_with=bind)
    blocks = sa.Table("ansich_content_blocks", metadata, autoload_with=bind)
    available_blocks = set(bind.execute(sa.select(blocks.c.entity_id)).scalars())
    existing = {(row.snapshot_id, int(row.ordinal)) for row in bind.execute(sa.select(memberships.c.snapshot_id, memberships.c.ordinal))}
    state_cache: dict[str, tuple[ContextStateItem, ...]] = {}

    def materialize(
        state_id: str,
        visited: frozenset[str] = frozenset(),
    ) -> tuple[ContextStateItem, ...]:
        if state_id in state_cache:
            return state_cache[state_id]
        if state_id in visited:
            raise ValueError("ContextState parent cycle detected during migration")
        state = bind.execute(sa.select(states).where(states.c.state_id == state_id)).mappings().one_or_none()
        if state is None or state["created_obs_id"] is None:
            return ()
        if bool(state["is_checkpoint"]):
            rows = bind.execute(sa.select(checkpoints).where(checkpoints.c.state_id == state_id).order_by(checkpoints.c.ordinal)).mappings()
            items = tuple(
                ContextStateItem(
                    ordinal=int(row["ordinal"]),
                    channel=row["channel"],
                    role=row["role"],
                    message_id=row["message_id"],
                    source_identity=row["source_identity"],
                    name=row["name"],
                    block_id=row["block_id"],
                    visible_bytes=int(row["visible_bytes"]),
                    estimated_tokens=int(row["estimated_tokens"]),
                    metadata=dict(row["metadata_json"] or {}),
                )
                for row in rows
            )
        else:
            parent_state_id = state["parent_state_id"]
            if not isinstance(parent_state_id, str):
                return ()
            parent = materialize(parent_state_id, visited | {state_id})
            operations: list[ContextStateDelta] = []
            for row in bind.execute(sa.select(deltas).where(deltas.c.state_id == state_id).order_by(deltas.c.operation_ordinal)).mappings():
                item = None
                if row["block_id"] is not None:
                    item = ContextStateItem(
                        ordinal=int(row["target_ordinal"] or 0),
                        channel=row["channel"],
                        role=row["role"],
                        message_id=row["message_id"],
                        source_identity=row["source_identity"],
                        name=row["name"],
                        block_id=row["block_id"],
                        visible_bytes=int(row["visible_bytes"] or 0),
                        estimated_tokens=int(row["estimated_tokens"] or 0),
                        metadata=dict(row["metadata_json"] or {}),
                    )
                operations.append(
                    ContextStateDelta(
                        op=row["operation"],
                        source_ordinal=row["source_ordinal"],
                        target_ordinal=row["target_ordinal"],
                        item=item,
                    )
                )
            items = materialize_context_state(
                parent,
                tuple(operations),
                item_count=int(state["item_count"]),
            )
        state_cache[state_id] = items
        return items

    for snapshot in bind.execute(sa.select(snapshots)).mappings():
        state_id = snapshot["state_id"]
        if isinstance(state_id, str):
            try:
                items = materialize(state_id)
            except ValueError:
                items = ()
            pairs = [(item.ordinal, item.block_id) for item in items]
        else:
            pairs = [
                (int(row.ordinal), row.content_block_id)
                for row in bind.execute(
                    sa.select(
                        snapshot_items.c.ordinal,
                        snapshot_items.c.content_block_id,
                    ).where(snapshot_items.c.snapshot_id == snapshot["entity_id"])
                )
            ]
        for ordinal, block_id in pairs:
            key = (snapshot["entity_id"], ordinal)
            if key in existing or block_id not in available_blocks:
                continue
            bind.execute(
                sa.insert(memberships).values(
                    snapshot_id=snapshot["entity_id"],
                    ordinal=ordinal,
                    content_block_id=block_id,
                )
            )
            existing.add(key)


def upgrade() -> None:
    safe_add_column(
        "ansich_content_block_derivations",
        sa.Column(
            "source_role",
            sa.String(length=16),
            nullable=False,
            server_default="source",
        ),
    )
    safe_add_column(
        "ansich_content_block_derivations",
        sa.Column("ordinal", sa.Integer(), nullable=True),
    )
    if sa.inspect(op.get_bind()).has_table("ansich_content_block_derivations"):
        with op.batch_alter_table("ansich_content_block_derivations") as batch:
            batch.alter_column(
                "source_role",
                existing_type=sa.String(length=16),
                existing_nullable=False,
                server_default=None,
            )
        indexes = _index_names("ansich_content_block_derivations")
        if "ix_ansich_derivations_derived_source" not in indexes:
            op.create_index(
                "ix_ansich_derivations_derived_source",
                "ansich_content_block_derivations",
                ["derived_block_id", "source_block_id"],
            )
        if "ix_ansich_derivations_source_derived" not in indexes:
            op.create_index(
                "ix_ansich_derivations_source_derived",
                "ansich_content_block_derivations",
                ["source_block_id", "derived_block_id"],
            )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ansich_block_producers"):
        op.create_table(
            "ansich_block_producers",
            sa.Column("block_id", sa.String(length=36), nullable=False),
            sa.Column("producer_kind", sa.String(length=64), nullable=False),
            sa.Column("producer_entity_id", sa.String(length=36), nullable=True),
            sa.Column("producer_obs_id", sa.String(length=36), nullable=False),
            sa.ForeignKeyConstraint(
                ["block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["producer_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("block_id"),
            sa.UniqueConstraint("producer_obs_id"),
        )
        op.create_index(
            "ix_ansich_block_producers_entity",
            "ansich_block_producers",
            ["producer_kind", "producer_entity_id"],
        )

    if not sa.inspect(op.get_bind()).has_table("ansich_context_compressions"):
        op.create_table(
            "ansich_context_compressions",
            sa.Column("entity_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("operation_id", sa.String(length=36), nullable=True),
            sa.Column("summary_block_id", sa.String(length=36), nullable=False),
            sa.Column("before_tokens", sa.BigInteger(), nullable=False),
            sa.Column("after_tokens", sa.BigInteger(), nullable=False),
            sa.Column("before_visible_bytes", sa.BigInteger(), nullable=False),
            sa.Column("after_visible_bytes", sa.BigInteger(), nullable=False),
            sa.Column("algorithm", sa.String(length=64), nullable=False),
            sa.Column("algorithm_version", sa.String(length=32), nullable=False),
            sa.Column("source_obs_id", sa.String(length=36), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="complete",
            ),
            sa.ForeignKeyConstraint(
                ["entity_id"],
                ["ansich_entities.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["ansich_tasks.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["summary_block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["source_obs_id"],
                ["ansich_observations.obs_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("entity_id"),
            sa.UniqueConstraint("source_obs_id"),
        )
        op.create_index(
            "ix_ansich_context_compressions_task",
            "ansich_context_compressions",
            ["task_id", "source_obs_id"],
        )

    if not sa.inspect(op.get_bind()).has_table("ansich_context_compression_items"):
        op.create_table(
            "ansich_context_compression_items",
            sa.Column("compression_id", sa.String(length=36), nullable=False),
            sa.Column("disposition", sa.String(length=16), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("block_id", sa.String(length=36), nullable=False),
            sa.ForeignKeyConstraint(
                ["compression_id"],
                ["ansich_context_compressions.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("compression_id", "disposition", "ordinal"),
        )
        op.create_index(
            "ix_ansich_context_compression_items_block",
            "ansich_context_compression_items",
            ["block_id", "compression_id"],
        )

    if not sa.inspect(op.get_bind()).has_table("ansich_context_snapshot_block_memberships"):
        op.create_table(
            "ansich_context_snapshot_block_memberships",
            sa.Column("snapshot_id", sa.String(length=36), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("content_block_id", sa.String(length=36), nullable=False),
            sa.ForeignKeyConstraint(
                ["snapshot_id"],
                ["ansich_context_snapshots.entity_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["content_block_id"],
                ["ansich_content_blocks.entity_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("snapshot_id", "ordinal"),
        )
        op.create_index(
            "ix_ansich_snapshot_block_memberships_block",
            "ansich_context_snapshot_block_memberships",
            ["content_block_id", "snapshot_id"],
        )

    if sa.inspect(op.get_bind()).has_table("ansich_context_snapshot_items"):
        indexes = _index_names("ansich_context_snapshot_items")
        if "ix_ansich_context_snapshot_items_block_snapshot" not in indexes:
            op.create_index(
                "ix_ansich_context_snapshot_items_block_snapshot",
                "ansich_context_snapshot_items",
                ["content_block_id", "snapshot_id"],
            )
    _backfill_block_producers()
    _backfill_snapshot_block_memberships()


def downgrade() -> None:
    for table in (
        "ansich_context_snapshot_block_memberships",
        "ansich_context_compression_items",
        "ansich_context_compressions",
        "ansich_block_producers",
    ):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
    if sa.inspect(op.get_bind()).has_table("ansich_context_snapshot_items"):
        indexes = _index_names("ansich_context_snapshot_items")
        if "ix_ansich_context_snapshot_items_block_snapshot" in indexes:
            op.drop_index(
                "ix_ansich_context_snapshot_items_block_snapshot",
                table_name="ansich_context_snapshot_items",
            )
    if sa.inspect(op.get_bind()).has_table("ansich_content_block_derivations"):
        indexes = _index_names("ansich_content_block_derivations")
        for index_name in (
            "ix_ansich_derivations_source_derived",
            "ix_ansich_derivations_derived_source",
        ):
            if index_name in indexes:
                op.drop_index(
                    index_name,
                    table_name="ansich_content_block_derivations",
                )
    safe_drop_column("ansich_content_block_derivations", "ordinal")
    safe_drop_column("ansich_content_block_derivations", "source_role")
