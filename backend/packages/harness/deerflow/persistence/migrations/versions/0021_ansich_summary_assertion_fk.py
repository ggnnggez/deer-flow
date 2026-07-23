"""Keep Ansich task summaries when their belief assertion is removed.

Revision ID: 0021_ansich_summary_assertion_fk
Revises: 0020_ansich_scope_safety
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_ansich_summary_assertion_fk"
down_revision: str | Sequence[str] | None = "0020_ansich_scope_safety"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
_LEGACY_ASSERTION_FK = "fk_ansich_task_summaries_assertion_id_ansich_belief_assertions"
_ASSERTION_FK = "fk_ansich_task_summary_assertion"


def _assertion_fk_name() -> str:
    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys("ansich_task_summaries"):
        if foreign_key["constrained_columns"] == ["assertion_id"] and foreign_key["referred_table"] == "ansich_belief_assertions":
            return foreign_key["name"] or _LEGACY_ASSERTION_FK
    raise RuntimeError("ansich_task_summaries.assertion_id foreign key is missing")


def upgrade() -> None:
    assertion_fk = _assertion_fk_name()
    with op.batch_alter_table(
        "ansich_task_summaries",
        naming_convention=_NAMING_CONVENTION,
    ) as batch:
        batch.drop_constraint(assertion_fk, type_="foreignkey")
        batch.alter_column(
            "assertion_id",
            existing_type=sa.String(36),
            existing_nullable=False,
            nullable=True,
        )
        batch.create_foreign_key(
            _ASSERTION_FK,
            "ansich_belief_assertions",
            ["assertion_id"],
            ["assertion_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM ansich_task_summaries WHERE assertion_id IS NULL"))
    assertion_fk = _assertion_fk_name()
    with op.batch_alter_table(
        "ansich_task_summaries",
        naming_convention=_NAMING_CONVENTION,
    ) as batch:
        batch.drop_constraint(assertion_fk, type_="foreignkey")
        batch.alter_column(
            "assertion_id",
            existing_type=sa.String(36),
            existing_nullable=True,
            nullable=False,
        )
        batch.create_foreign_key(
            _LEGACY_ASSERTION_FK,
            "ansich_belief_assertions",
            ["assertion_id"],
            ["assertion_id"],
        )
