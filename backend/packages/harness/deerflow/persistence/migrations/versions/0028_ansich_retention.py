"""Add Ansich retention state, payload tombstones, and active component versions.

The P11-C batch's only migration, so it carries every schema change the batch
makes:

- ``ansich_payloads`` gains ``deleted_at`` / ``policy`` and its ``body`` becomes
  nullable, under a new ``ck_ansich_payload_tombstone_one_of`` check. Retention's
  first tier deletes the *body* and keeps the row: body NULL plus a
  ``deleted_at`` is a tombstone, body present with no ``deleted_at`` is a live
  payload, and the check makes the other two combinations unwritable. Both are
  states a reader must be able to tell apart — a body-less row with no tombstone
  stays a corruption signal (a loud raise), while a tombstone is an expected
  policy outcome (an explicit expired state). ``sha256`` and ``byte_size`` are
  untouched on purpose: they are the tombstone's lineage half.

- ``ansich_retention_state`` — one row (``id = 1``, pinned by a check
  constraint) holding the per-tier resume cursors, the Observation-tier
  deletion horizon, and the last run's timestamps and policy snapshot. The
  cursors say how far a pass walked; the horizon is a stronger claim, namely
  the contiguous prefix that is fully deleted, and it is what receipt
  resolution consults so retention cannot flip a once-accepted receipt to
  ``failed``.

- ``ansich_active_versions`` — which version of a versioned component
  (``projector`` / ``resolver``) is authoritative, absent row meaning the code
  default. ``audit_obs_id`` points at the ``operator.action_*`` Observation
  that recorded the switch, with ``ON DELETE SET NULL`` so an expiring audit
  anchor degrades the evidence pointer without either reverting the selection
  (CASCADE) or pinning an Observation out of retention forever (RESTRICT).

- One data step, and the reason it is here rather than in code: it deletes
  every ``ansich_active_task_read_model`` row.

The data step (F10-32)
----------------------

Rows written before P11-B's health merge carry the *old* ``projection_watermark``
stamp — that worker's highest projected ``ingest_seq`` — while every tick since
stamps the store-wide continuity mark, which is at or below it. The publish
guard skips any row whose stored basis is above the tick's, so while any job is
durably ``failed`` such a row is never updated again: visibly (one DEBUG line
per tick) for a Task still running, and *silently* for a Task that has since
stopped, because the guarded sweep also refuses to delete it. It then keeps
reading as ``running`` forever.

Until now that was tolerable only because of a premise with an expiry date — no
deployed population carried the old stamp, since every P11-B commit was
unpushed — and the premise fails silently at the first deploy of that branch
with no test going red. Deleting the rows kills the premise instead of
re-adjudicating it at deploy time. It is safe because these rows are a pure
read model: the next periodic operations tick rebuilds them from the Task
projections, exactly as ``rebuild_projections()`` already deletes them
wholesale. The whole cost is one to two seconds of an empty Running lens on the
first startup after the upgrade.

Revision ID: 0028_ansich_retention
Revises: 0027_ansich_lease_generation
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column

revision: str = "0028_ansich_retention"
down_revision: str | Sequence[str] | None = "0027_ansich_lease_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAYLOADS_TABLE = "ansich_payloads"
_TOMBSTONE_CHECK = "ck_ansich_payload_tombstone_one_of"
_TOMBSTONE_CONDITION = "(body IS NOT NULL AND deleted_at IS NULL) OR (body IS NULL AND deleted_at IS NOT NULL)"
_ACTIVE_TASK_READ_MODEL = "ansich_active_task_read_model"


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    """Create a table unless a legacy ``create_all`` already did."""
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *elements)


def _drop_table(name: str) -> None:
    if sa.inspect(op.get_bind()).has_table(name):
        op.drop_table(name)


def _body_is_nullable() -> bool | None:
    """``None`` when the table is absent, else the current nullability of ``body``."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_PAYLOADS_TABLE):
        return None
    for column in inspector.get_columns(_PAYLOADS_TABLE):
        if column["name"] == "body":
            return bool(column.get("nullable", True))
    return None


def _has_tombstone_check() -> bool:
    """True when the check is already present.

    ``get_check_constraints`` is implemented on both dialects this repo
    supports — natively on PostgreSQL, by parsing the stored ``CREATE TABLE``
    on SQLite — so the guard does not silently degrade to "always create" on
    one of them and duplicate the constraint on a re-run.
    """
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_PAYLOADS_TABLE):
        return False
    return any(constraint.get("name") == _TOMBSTONE_CHECK for constraint in inspector.get_check_constraints(_PAYLOADS_TABLE))


def upgrade() -> None:
    safe_add_column(_PAYLOADS_TABLE, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    safe_add_column(_PAYLOADS_TABLE, sa.Column("policy", sa.String(length=128), nullable=True))

    body_nullable = _body_is_nullable()
    needs_check = not _has_tombstone_check()
    if body_nullable is not None and (body_nullable is False or needs_check):
        # SQLite cannot drop NOT NULL or add a CHECK in place; ``batch_alter_table``
        # recreates the table there and issues plain ALTERs everywhere else. The
        # migration engine (``migrations/env.py``) builds its own connection and
        # never enables ``PRAGMA foreign_keys``, so the SQLite recreate does not
        # trip ``ansich_observations.payload_ref_id``'s RESTRICT.
        with op.batch_alter_table(_PAYLOADS_TABLE) as batch:
            if body_nullable is False:
                batch.alter_column(
                    "body",
                    existing_type=sa.LargeBinary(),
                    existing_nullable=False,
                    nullable=True,
                )
            if needs_check:
                batch.create_check_constraint(_TOMBSTONE_CHECK, _TOMBSTONE_CONDITION)

    _create_table(
        "ansich_retention_state",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("payload_cursor", sa.String(length=36), nullable=True),
        sa.Column("observation_cursor", sa.BigInteger(), nullable=True),
        sa.Column("structural_cursor", sa.String(length=36), nullable=True),
        sa.Column("observation_horizon_ingest_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_run_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_policy", sa.JSON(none_as_null=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_ansich_retention_state_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table(
        "ansich_active_versions",
        sa.Column("component_kind", sa.String(length=32), nullable=False),
        sa.Column("component_name", sa.String(length=64), nullable=False),
        sa.Column("active_version", sa.String(length=32), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_by", sa.String(length=128), nullable=False),
        sa.Column("audit_obs_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["audit_obs_id"],
            ["ansich_observations.obs_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("component_kind", "component_name"),
    )

    # F10-32's data step. See the module docstring for why this is a delete and
    # not a backfill: the stamp it would have to repair is one worker's private
    # progress, which no longer has a store-wide meaning to be repaired into.
    if sa.inspect(op.get_bind()).has_table(_ACTIVE_TASK_READ_MODEL):
        op.execute(sa.text(f"DELETE FROM {_ACTIVE_TASK_READ_MODEL}"))


def _payloads_table_after_upgrade() -> sa.Table:
    """The post-upgrade ``ansich_payloads``, spelled out for ``copy_from``.

    The downgrade drops a CHECK *and* the two columns it names in one batch, and
    on SQLite that is a table recreate. Reflecting the source table there is not
    good enough for this: whether a reflected ``Table`` carries its CHECK
    constraints is dialect-dependent, and the two failure modes are opposite —
    reflect it and the recreate rebuilds a CHECK over columns this same batch is
    dropping; miss it and ``drop_constraint`` has nothing to drop. Stating the
    source table removes the guess.
    """
    metadata = sa.MetaData()
    return sa.Table(
        _PAYLOADS_TABLE,
        metadata,
        sa.Column("payload_id", sa.String(length=36), primary_key=True),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("encoding", sa.String(length=32), nullable=False),
        sa.Column("compression", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_TOMBSTONE_CONDITION, name=_TOMBSTONE_CHECK),
    )


def downgrade() -> None:
    # The read-model rows this migration deleted are not restored: they never
    # were a source of record, and the next operations tick republishes them on
    # either side of the downgrade.
    _drop_table("ansich_active_versions")
    _drop_table("ansich_retention_state")

    if _body_is_nullable() is None:
        return

    # The pre-0028 schema cannot express an expired payload, so tombstones
    # cannot survive the downgrade. Deleting them is the honest option; on
    # PostgreSQL ``ansich_observations.payload_ref_id``'s RESTRICT turns a
    # tombstone that is still referenced into a loud refusal, which is what it
    # should be — the alternative, writing an empty body, would resurrect the
    # row as a *readable* payload and let a reader validate ``{}`` into a
    # verdict the evidence never supported. An operator who genuinely wants the
    # downgrade removes the owning Observations first.
    op.execute(sa.text(f"DELETE FROM {_PAYLOADS_TABLE} WHERE body IS NULL"))

    with op.batch_alter_table(_PAYLOADS_TABLE, copy_from=_payloads_table_after_upgrade()) as batch:
        if _has_tombstone_check():
            batch.drop_constraint(_TOMBSTONE_CHECK, type_="check")
        batch.drop_column("policy")
        batch.drop_column("deleted_at")
        batch.alter_column(
            "body",
            existing_type=sa.LargeBinary(),
            existing_nullable=True,
            nullable=False,
        )
