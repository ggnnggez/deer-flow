"""Collapse historical per-tick wall_time contributions into per-source watermarks.

Phase 8 stored one durable ``ansich_usage_contributions`` row for every
``task.heartbeat`` tick, so a long-lived Task accumulated one wall_time row per
tick per aggregate and every summary refresh rescanned all of them (phase-8
review followup M2). ``wall_time_ms`` is a max-type dimension — each tick
re-reports the *cumulative* elapsed time — so only the maximum per
``(aggregate_task_id, source_task_id)`` carries information.

This revision deletes the dominated heartbeat-sourced rows, leaving exactly one
high-water row per pair, which is what the reworked projector maintains from
here on. It is a data-only revision: no schema object changes.

Value-preserving by construction: every wall_time consumer reduces the rows of
one ``(aggregate, source)`` with ``max``, and deleting non-maximal rows leaves
that ``max`` untouched. ``ansich_task_usage`` summaries therefore stay correct
and are deliberately not rewritten. Terminal ``budget.consumed`` wall_time rows
(one per Task) are untouched so their own evidence survives beside the mark.

Revision ID: 0024_ansich_wall_time_watermarks
Revises: 0023_ansich_evaluations
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_ansich_wall_time_watermarks"
down_revision: str | Sequence[str] | None = "0023_ansich_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Mirrors ``ansich.usage.HIGH_WATER_USAGE_KINDS`` /
#: ``MAX_TYPE_USAGE_DIMENSIONS``. Migrations are pinned history, so the values
#: are inlined rather than imported: a later contract change must not silently
#: rewrite what this revision already did.
_HIGH_WATER_KIND = "task.heartbeat"
_MAX_TYPE_DIMENSION = "wall_time_ms"

# Delete every heartbeat-sourced wall_time contribution that a strictly greater
# sibling of the same (aggregate, source) dominates, using the same
# ``(delta, as_of, source_obs_id)`` total order the projector applies, so both
# sides converge on the identical surviving row.
_COLLAPSE_STATEMENT = """
DELETE FROM ansich_usage_contributions
WHERE dimension = :dimension
  AND EXISTS (
      SELECT 1
      FROM ansich_observations AS own_observation
      WHERE own_observation.obs_id = ansich_usage_contributions.source_obs_id
        AND own_observation.kind = :kind
  )
  AND EXISTS (
      SELECT 1
      FROM ansich_usage_contributions AS sibling
      JOIN ansich_observations AS sibling_observation
        ON sibling_observation.obs_id = sibling.source_obs_id
      WHERE sibling.aggregate_task_id = ansich_usage_contributions.aggregate_task_id
        AND sibling.source_task_id = ansich_usage_contributions.source_task_id
        AND sibling.dimension = ansich_usage_contributions.dimension
        AND sibling_observation.kind = :kind
        AND (
            sibling.delta > ansich_usage_contributions.delta
            OR (
                sibling.delta = ansich_usage_contributions.delta
                AND sibling.as_of > ansich_usage_contributions.as_of
            )
            OR (
                sibling.delta = ansich_usage_contributions.delta
                AND sibling.as_of = ansich_usage_contributions.as_of
                AND sibling.source_obs_id > ansich_usage_contributions.source_obs_id
            )
        )
  )
"""


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Guarded like 0016/0023: a partially provisioned legacy database may not
    # carry both tables yet, and re-running the collapse must stay a no-op.
    if not inspector.has_table("ansich_usage_contributions"):
        return
    if not inspector.has_table("ansich_observations"):
        return
    op.execute(
        sa.text(_COLLAPSE_STATEMENT).bindparams(
            dimension=_MAX_TYPE_DIMENSION,
            kind=_HIGH_WATER_KIND,
        )
    )


def downgrade() -> None:
    """Reverse of a data-only collapse: nothing to undo structurally.

    The revision changes no schema object, so the schema downgrade is complete
    as a no-op. The deleted rows are not restored because they are rebuildable
    projection output, not source facts: the ``ansich_observations`` heartbeat
    ticks they were derived from are untouched, and ``rebuild_projections()``
    regenerates the contribution rows for whichever code version is running —
    per-tick rows before this change, high-water rows after it. This mirrors how
    0019 downgraded its own derived fan-out/inclusive rows.
    """
