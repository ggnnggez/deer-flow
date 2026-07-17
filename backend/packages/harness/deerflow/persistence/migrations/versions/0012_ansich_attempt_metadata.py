"""Split Ansich LLM usage from provider response metadata.

Revision ID: 0012_ansich_attempt_metadata
Revises: 0011_ansich_context_states
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0012_ansich_attempt_metadata"
down_revision: str | Sequence[str] | None = "0011_ansich_context_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _attempts_table() -> sa.Table | None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("ansich_llm_attempts"):
        return None
    return sa.Table("ansich_llm_attempts", sa.MetaData(), autoload_with=bind)


def upgrade() -> None:
    safe_add_column("ansich_llm_attempts", sa.Column("response_metadata_json", sa.JSON(), nullable=True))
    attempts = _attempts_table()
    if attempts is None:
        return
    bind = op.get_bind()
    rows = bind.execute(sa.select(attempts.c.attempt_id, attempts.c.usage_json)).mappings()
    for row in rows:
        stored = row["usage_json"]
        if not isinstance(stored, dict) or not ({"usage", "response_metadata"} & stored.keys()):
            continue
        bind.execute(
            sa.update(attempts)
            .where(attempts.c.attempt_id == row["attempt_id"])
            .values(
                usage_json=dict(stored.get("usage") or {}),
                response_metadata_json=dict(stored.get("response_metadata") or {}),
            )
        )


def downgrade() -> None:
    attempts = _attempts_table()
    if attempts is not None:
        bind = op.get_bind()
        rows = bind.execute(
            sa.select(
                attempts.c.attempt_id,
                attempts.c.usage_json,
                attempts.c.response_metadata_json,
            )
        ).mappings()
        for row in rows:
            if row["usage_json"] is None and row["response_metadata_json"] is None:
                continue
            bind.execute(
                sa.update(attempts)
                .where(attempts.c.attempt_id == row["attempt_id"])
                .values(
                    usage_json={
                        "usage": dict(row["usage_json"] or {}),
                        "response_metadata": dict(row["response_metadata_json"] or {}),
                    }
                )
            )
    safe_drop_column("ansich_llm_attempts", "response_metadata_json")
