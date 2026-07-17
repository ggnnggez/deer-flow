"""Persist stable Ansich content occurrences and snapshot source identity.

Revision ID: 0010_ansich_content_occurrences
Revises: 0009_ansich_content_blobs
Create Date: 2026-07-17
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0010_ansich_content_occurrences"
down_revision: str | Sequence[str] | None = "0009_ansich_content_blobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _decode_payload(row: sa.Row, payloads: sa.Table) -> dict | None:
    if isinstance(row.payload_json, dict):
        return dict(row.payload_json)
    if row.payload_ref_id is None:
        return None
    payload_row = op.get_bind().execute(sa.select(payloads).where(payloads.c.payload_id == row.payload_ref_id)).mappings().first()
    if payload_row is None:
        return None
    decoded = json.loads(bytes(payload_row["body"]).decode(payload_row["encoding"]))
    return dict(decoded) if isinstance(decoded, dict) else None


def _source_identity(item: dict) -> str | None:
    explicit = item.get("source_identity")
    if isinstance(explicit, str) and explicit:
        return explicit
    channel = item.get("channel")
    message_id = item.get("message_id")
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if channel == "message" and isinstance(message_id, str) and message_id:
        occurrence_seq = metadata.get("message_occurrence_seq", 1)
        if not isinstance(occurrence_seq, int):
            return None
        part_ordinal = metadata.get("part_ordinal")
        if isinstance(part_ordinal, int):
            return f"message:{message_id}:occurrence:{occurrence_seq}:content:{part_ordinal}"
        tool_call_ordinal = metadata.get("tool_call_ordinal")
        if isinstance(tool_call_ordinal, int):
            return f"message:{message_id}:occurrence:{occurrence_seq}:tool-call:{tool_call_ordinal}"
    name = item.get("name")
    if channel == "tool_schema" and isinstance(name, str) and name:
        return f"tool-schema:{name}"
    return None


def _backfill_occurrences_and_snapshot_identity() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    observations = sa.Table("ansich_observations", metadata, autoload_with=bind)
    payloads = sa.Table("ansich_payloads", metadata, autoload_with=bind)
    blocks = sa.Table("ansich_content_blocks", metadata, autoload_with=bind)
    occurrences = sa.Table("ansich_content_occurrences", metadata, autoload_with=bind)
    snapshot_items = sa.Table("ansich_context_snapshot_items", metadata, autoload_with=bind)
    missing_items = sa.Table("ansich_context_snapshot_missing_items", metadata, autoload_with=bind)
    source_by_block: dict[str, tuple[str, str]] = {}

    snapshot_observations = bind.execute(
        sa.select(
            observations.c.ingest_seq,
            observations.c.subject_id,
            observations.c.task_id,
            observations.c.payload_json,
            observations.c.payload_ref_id,
        )
        .where(observations.c.kind == "context.snapshotted")
        .order_by(observations.c.ingest_seq)
    ).all()
    for observation in snapshot_observations:
        payload = _decode_payload(observation, payloads)
        if payload is None:
            continue
        for raw_item in payload.get("items", []):
            if not isinstance(raw_item, dict):
                continue
            ordinal = raw_item.get("ordinal")
            block_id = raw_item.get("block_id")
            if not isinstance(ordinal, int) or not isinstance(block_id, str):
                continue
            source_identity = _source_identity(raw_item)
            message_id = raw_item.get("message_id") if isinstance(raw_item.get("message_id"), str) else None
            values = {"message_id": message_id, "source_identity": source_identity}
            bind.execute(
                sa.update(snapshot_items)
                .where(
                    snapshot_items.c.snapshot_id == observation.subject_id,
                    snapshot_items.c.ordinal == ordinal,
                )
                .values(**values)
            )
            bind.execute(
                sa.update(missing_items)
                .where(
                    missing_items.c.snapshot_id == observation.subject_id,
                    missing_items.c.ordinal == ordinal,
                )
                .values(source_identity=source_identity)
            )
            if source_identity is not None:
                source_by_block.setdefault(block_id, (observation.task_id, source_identity))

    content_rows = bind.execute(
        sa.select(
            observations.c.ingest_seq,
            observations.c.obs_id,
            observations.c.task_id,
            observations.c.subject_id,
            observations.c.recorded_at,
            observations.c.payload_json,
            observations.c.payload_ref_id,
            blocks.c.content_hash,
            blocks.c.kind,
        )
        .join(blocks, blocks.c.entity_id == observations.c.subject_id)
        .where(observations.c.kind == "content.produced")
        .order_by(observations.c.ingest_seq)
    ).all()
    seen_blocks: set[str] = set()
    seen_keys: set[tuple[str, str, str, str]] = set()
    for observation in content_rows:
        payload = _decode_payload(observation, payloads)
        source_identity = payload.get("source_identity") if isinstance(payload, dict) else None
        if not isinstance(source_identity, str) or not source_identity:
            candidate = source_by_block.get(observation.subject_id)
            source_identity = candidate[1] if candidate is not None and candidate[0] == observation.task_id else None
        if source_identity is None:
            continue
        key = (observation.task_id, source_identity, observation.content_hash, observation.kind)
        if key in seen_keys or observation.subject_id in seen_blocks:
            continue
        bind.execute(
            sa.insert(occurrences).values(
                task_id=observation.task_id,
                source_identity=source_identity,
                content_hash=observation.content_hash,
                kind=observation.kind,
                block_id=observation.subject_id,
                producer_obs_id=observation.obs_id,
                created_at=observation.recorded_at,
            )
        )
        seen_keys.add(key)
        seen_blocks.add(observation.subject_id)


def upgrade() -> None:
    safe_add_column(
        "ansich_context_snapshot_items",
        sa.Column("message_id", sa.String(length=256), nullable=True),
    )
    safe_add_column(
        "ansich_context_snapshot_items",
        sa.Column("source_identity", sa.String(length=512), nullable=True),
    )
    safe_add_column(
        "ansich_context_snapshot_missing_items",
        sa.Column("source_identity", sa.String(length=512), nullable=True),
    )
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ansich_content_occurrences"):
        op.create_table(
            "ansich_content_occurrences",
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("source_identity", sa.String(length=512), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("block_id", sa.String(length=36), nullable=False),
            sa.Column("producer_obs_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["block_id"], ["ansich_content_blocks.entity_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["producer_obs_id"], ["ansich_observations.obs_id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["task_id"], ["ansich_tasks.entity_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("task_id", "source_identity", "content_hash", "kind"),
            sa.UniqueConstraint("block_id"),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("ansich_content_occurrences")}
    if "ix_ansich_content_occurrences_task_source" not in indexes:
        op.create_index(
            "ix_ansich_content_occurrences_task_source",
            "ansich_content_occurrences",
            ["task_id", "source_identity"],
            unique=False,
        )
    if "ix_ansich_content_occurrences_block" not in indexes:
        op.create_index(
            "ix_ansich_content_occurrences_block",
            "ansich_content_occurrences",
            ["block_id"],
            unique=False,
        )
    _backfill_occurrences_and_snapshot_identity()


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ansich_content_occurrences"):
        op.drop_table("ansich_content_occurrences")
    safe_drop_column("ansich_context_snapshot_missing_items", "source_identity")
    safe_drop_column("ansich_context_snapshot_items", "source_identity")
    safe_drop_column("ansich_context_snapshot_items", "message_id")
