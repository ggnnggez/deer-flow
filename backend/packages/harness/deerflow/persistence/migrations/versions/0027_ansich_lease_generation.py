"""Add Ansich lease generations and a per-projector status index.

Two additive columns and one index, no behaviour change on their own:

- ``ansich_projection_jobs.lease_generation`` /
  ``ansich_assessor_jobs.lease_generation`` — a monotonic per-job claim
  counter. Both job tables already carry ``lease_owner``, but that field alone
  cannot make a compare-and-set sound: the owner id is one ``uuid4`` minted per
  service instance and stable for the whole process lifetime, so a worker whose
  lease expired mid-work can claim the *same* job again and read its own id
  back out of ``lease_owner``. That is an ABA — the field returned to a value
  it already held, through a state the stale writer must not write into — and
  an owner-only ``WHERE lease_owner = :me`` would let the stale attempt commit
  over the fresh claim. A CAS therefore has to compare
  ``(lease_owner, lease_generation)`` together. The claim/complete paths are
  not touched here; adopting the column is a separate change.
- ``ix_ansich_projection_jobs_projector_status (projector_name, status)`` —
  supports the per-projector status-split counts the health merge reads. That
  read groups the jobs table by ``(projector_name, status)``, which without
  this index is a full scan of every job row ever written.

Both columns land ``NOT NULL DEFAULT 0``: a column added without a default
cannot be made ``NOT NULL`` over rows that predate it, so every existing job
starts at generation zero.

Revision ID: 0027_ansich_lease_generation
Revises: 0026_ansich_environment
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0027_ansich_lease_generation"
down_revision: str | Sequence[str] | None = "0026_ansich_environment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTOR_STATUS_INDEX = "ix_ansich_projection_jobs_projector_status"
_PROJECTION_JOBS_TABLE = "ansich_projection_jobs"


def _lease_generation_column() -> sa.Column:
    """A fresh ``sa.Column`` per call: alembic mutates the object it appends."""
    return sa.Column("lease_generation", sa.BigInteger(), nullable=False, server_default="0")


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    """Create an index unless its table is absent or it already exists."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return
    if name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(name, table_name, columns, unique=False)


def _drop_index(name: str, table_name: str) -> None:
    """Drop an index only when its table and the index itself are present."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return
    if name in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.drop_index(name, table_name=table_name)


def upgrade() -> None:
    safe_add_column("ansich_projection_jobs", _lease_generation_column())
    safe_add_column("ansich_assessor_jobs", _lease_generation_column())
    _create_index(
        _PROJECTOR_STATUS_INDEX,
        _PROJECTION_JOBS_TABLE,
        ["projector_name", "status"],
    )


def downgrade() -> None:
    _drop_index(_PROJECTOR_STATUS_INDEX, _PROJECTION_JOBS_TABLE)
    safe_drop_column("ansich_assessor_jobs", "lease_generation")
    safe_drop_column("ansich_projection_jobs", "lease_generation")
