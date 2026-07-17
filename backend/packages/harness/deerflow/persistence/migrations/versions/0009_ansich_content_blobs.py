"""Deduplicate Ansich content payload values without merging occurrences.

Revision ID: 0009_ansich_content_blobs
Revises: 0008_ansich_context_resilience
Create Date: 2026-07-17
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0009_ansich_content_blobs"
down_revision: str | Sequence[str] | None = "0008_ansich_context_resilience"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CANONICALIZATION_VERSION = "1"
_INLINE_PAYLOAD_MAX_BYTES = 65_536


def _canonical_content_bytes(body: object) -> tuple[str, bytes]:
    if isinstance(body, str):
        return "text/plain; charset=utf-8", body.encode("utf-8")
    return (
        "application/json",
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )


def _blob_key(content_type: str, body: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(f"ansich-content:{_CANONICALIZATION_VERSION}:{content_type}\0".encode())
    digest.update(body)
    return digest.hexdigest()


def _decode_observation_payload(row: sa.Row, payloads: sa.Table) -> dict | None:
    if isinstance(row.payload_json, dict):
        return dict(row.payload_json)
    if row.payload_ref_id is None:
        return None
    payload_row = op.get_bind().execute(sa.select(payloads).where(payloads.c.payload_id == row.payload_ref_id)).mappings().first()
    if payload_row is None:
        return None
    decoded = json.loads(bytes(payload_row["body"]).decode(payload_row["encoding"]))
    return dict(decoded) if isinstance(decoded, dict) else None


def _store_observation_payload(row: sa.Row, payload: dict, observations: sa.Table, payloads: sa.Table) -> None:
    if row.payload_ref_id is None:
        op.get_bind().execute(sa.update(observations).where(observations.c.obs_id == row.obs_id).values(payload_json=payload))
        return
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    op.get_bind().execute(
        sa.update(payloads)
        .where(payloads.c.payload_id == row.payload_ref_id)
        .values(byte_size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), body=encoded)
    )


def _backfill_blobs() -> None:
    metadata = sa.MetaData()
    bind = op.get_bind()
    observations = sa.Table("ansich_observations", metadata, autoload_with=bind)
    payloads = sa.Table("ansich_payloads", metadata, autoload_with=bind)
    blocks = sa.Table("ansich_content_blocks", metadata, autoload_with=bind)
    blobs = sa.Table("ansich_content_blobs", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(
            blocks.c.entity_id,
            blocks.c.payload_obs_id,
            observations.c.obs_id,
            observations.c.payload_json,
            observations.c.payload_ref_id,
        ).join(observations, observations.c.obs_id == blocks.c.payload_obs_id)
    ).all()
    for row in rows:
        payload = _decode_observation_payload(row, payloads)
        if payload is None or "body" not in payload:
            continue
        body = payload["body"]
        content_type, content_bytes = _canonical_content_bytes(body)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        key = _blob_key(content_type, content_bytes)
        existing = bind.execute(sa.select(blobs.c.blob_key).where(blobs.c.blob_key == key)).scalar_one_or_none()
        if existing is None:
            inline_body = content_bytes
            blob_payload_ref_id = None
            if len(content_bytes) > _INLINE_PAYLOAD_MAX_BYTES:
                blob_payload_ref_id = str(uuid4())
                inline_body = None
                bind.execute(
                    sa.insert(payloads).values(
                        payload_id=blob_payload_ref_id,
                        content_type=content_type,
                        encoding="utf-8",
                        compression="none",
                        byte_size=len(content_bytes),
                        sha256=content_hash,
                        body=content_bytes,
                    )
                )
            bind.execute(
                sa.insert(blobs).values(
                    blob_key=key,
                    content_hash=content_hash,
                    byte_size=len(content_bytes),
                    content_type=content_type,
                    canonicalization_version=_CANONICALIZATION_VERSION,
                    inline_body=inline_body,
                    payload_ref_id=blob_payload_ref_id,
                    created_at=datetime.now(UTC),
                )
            )
        bind.execute(sa.update(blocks).where(blocks.c.entity_id == row.entity_id).values(blob_key=key))
        payload.pop("body", None)
        payload.update(
            {
                "blob_key": key,
                "content_type": content_type,
                "canonicalization_version": _CANONICALIZATION_VERSION,
            }
        )
        _store_observation_payload(row, payload, observations, payloads)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ansich_content_blobs"):
        op.create_table(
            "ansich_content_blobs",
            sa.Column("blob_key", sa.String(length=64), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("byte_size", sa.BigInteger(), nullable=False),
            sa.Column("content_type", sa.String(length=64), nullable=False),
            sa.Column("canonicalization_version", sa.String(length=16), nullable=False),
            sa.Column("inline_body", sa.LargeBinary(), nullable=True),
            sa.Column("payload_ref_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "(inline_body IS NOT NULL AND payload_ref_id IS NULL) OR (inline_body IS NULL AND payload_ref_id IS NOT NULL)",
                name="ck_ansich_content_blob_payload_one_of",
            ),
            sa.ForeignKeyConstraint(["payload_ref_id"], ["ansich_payloads.payload_id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("blob_key"),
            sa.UniqueConstraint(
                "content_hash",
                "byte_size",
                "content_type",
                "canonicalization_version",
                name="uq_ansich_content_blob_value",
            ),
        )
    safe_add_column(
        "ansich_content_blocks",
        sa.Column(
            "blob_key",
            sa.String(length=64),
            sa.ForeignKey("ansich_content_blobs.blob_key", ondelete="RESTRICT", name="fk_ansich_content_blocks_blob_key"),
            nullable=True,
        ),
    )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("ansich_content_blocks")}
    if "ix_ansich_content_blocks_blob" not in indexes:
        op.create_index("ix_ansich_content_blocks_blob", "ansich_content_blocks", ["blob_key"], unique=False)
    _backfill_blobs()


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("ansich_content_blocks"):
        indexes = {index["name"] for index in inspector.get_indexes("ansich_content_blocks")}
        if "ix_ansich_content_blocks_blob" in indexes:
            op.drop_index("ix_ansich_content_blocks_blob", table_name="ansich_content_blocks")
    safe_drop_column("ansich_content_blocks", "blob_key")
    if sa.inspect(op.get_bind()).has_table("ansich_content_blobs"):
        op.drop_table("ansich_content_blobs")
