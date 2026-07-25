"""Add typed Scope, authorization, effect, and safety conclusion storage.

Revision ID: 0020_ansich_scope_safety
Revises: 0019_ansich_task_tree_usage
Create Date: 2026-07-21
"""

from __future__ import annotations

import posixpath
from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0020_ansich_scope_safety"
down_revision: str | Sequence[str] | None = "0019_ansich_task_tree_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope_hash(scope_kind: str, external_ref: str) -> str:
    normalized = external_ref.strip()
    if scope_kind in {"workspace", "sandbox"}:
        normalized = posixpath.normpath(normalized.replace("\\", "/"))
    return sha256(f"ansich-scope-v1\0{scope_kind}\0{normalized}".encode()).hexdigest()


def _scope_label(scope_kind: str, external_ref: str) -> str:
    if scope_kind not in {"workspace", "sandbox"}:
        return external_ref[:256]
    normalized = posixpath.normpath(external_ref.replace("\\", "/"))
    leaf = posixpath.basename(normalized)
    return (leaf or scope_kind)[:256]


def _scope_entity_id(scope_kind: str, external_ref_hash: str) -> str:
    digest = sha256(f"ansich-scope-entity-v1\0{scope_kind}\0{external_ref_hash}".encode()).digest()
    return str(UUID(bytes=digest[:16], version=4))


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return column in {existing["name"] for existing in inspector.get_columns(table)}


def _create_table(name: str, *elements: sa.SchemaItem) -> None:
    """Create a table unless a full ``create_all`` already produced it."""

    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *elements)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return
    if name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    # A database provisioned by a full ``Base.metadata.create_all`` -- the empty
    # bootstrap branch, or a legacy DB whose ``alembic_version`` was lost and is
    # re-stamped at 0001 -- already carries every column, constraint, and table
    # this revision adds. Guard each schema step with an existence check, the
    # same style 0013-0019 use, so the revision is a no-op there instead of
    # failing with "duplicate column name: external_ref_hash".
    scopes_need_columns = not _has_column("ansich_scopes", "external_ref_hash")
    relations_need_columns = not _has_column("ansich_relations", "relation_role")

    if scopes_need_columns:
        with op.batch_alter_table("ansich_scopes") as batch:
            batch.add_column(sa.Column("external_ref_hash", sa.String(64)))
            batch.add_column(sa.Column("display_label", sa.String(256)))
            batch.add_column(sa.Column("parent_scope_id", sa.String(36)))
            batch.add_column(sa.Column("created_obs_id", sa.String(36)))

    connection = op.get_bind()
    legacy_scopes = connection.execute(
        sa.text(
            """
            SELECT scopes.entity_id, scopes.scope_kind, scopes.scope_value,
                   entities.discovered_obs_id
            FROM ansich_scopes AS scopes
            JOIN ansich_entities AS entities
              ON entities.entity_id = scopes.entity_id
            """
        )
    ).mappings()
    for scope in legacy_scopes:
        raw_value = str(scope["scope_value"])
        connection.execute(
            sa.text(
                """
                UPDATE ansich_scopes
                SET external_ref_hash = :external_ref_hash,
                    display_label = :display_label,
                    created_obs_id = :created_obs_id
                WHERE entity_id = :entity_id
                """
            ),
            {
                "entity_id": scope["entity_id"],
                "external_ref_hash": _scope_hash(scope["scope_kind"], raw_value),
                "display_label": _scope_label(scope["scope_kind"], raw_value),
                "created_obs_id": scope["discovered_obs_id"],
            },
        )

    # Scope IDs were random before Phase 9. Rewrite them before the new
    # authorization FKs exist so future projection rebuilds reproduce the same
    # identity from Task admission observations.
    migrated_scopes = list(
        connection.execute(
            sa.text(
                """
                SELECT entity_id, scope_kind, scope_value, external_ref_hash,
                       display_label, created_obs_id
                FROM ansich_scopes
                """
            )
        ).mappings()
    )
    for scope in migrated_scopes:
        old_scope_id = str(scope["entity_id"])
        new_scope_id = _scope_entity_id(str(scope["scope_kind"]), str(scope["external_ref_hash"]))
        if old_scope_id == new_scope_id:
            continue
        connection.execute(
            sa.text(
                """
                INSERT INTO ansich_entities (
                    entity_id, entity_type, discovered_obs_id
                ) VALUES (
                    :entity_id, 'scope', :discovered_obs_id
                )
                """
            ),
            {
                "entity_id": new_scope_id,
                "discovered_obs_id": scope["created_obs_id"],
            },
        )
        connection.execute(
            sa.text("UPDATE ansich_relations SET subject_id = :new_id WHERE subject_id = :old_id"),
            {"new_id": new_scope_id, "old_id": old_scope_id},
        )
        connection.execute(
            sa.text("UPDATE ansich_relations SET object_id = :new_id WHERE object_id = :old_id"),
            {"new_id": new_scope_id, "old_id": old_scope_id},
        )
        connection.execute(
            sa.text("DELETE FROM ansich_scopes WHERE entity_id = :entity_id"),
            {"entity_id": old_scope_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO ansich_scopes (
                    entity_id, scope_kind, scope_value, external_ref_hash,
                    display_label, parent_scope_id, created_obs_id
                ) VALUES (
                    :entity_id, :scope_kind, :scope_value, :external_ref_hash,
                    :display_label, NULL, :created_obs_id
                )
                """
            ),
            {
                "entity_id": new_scope_id,
                "scope_kind": scope["scope_kind"],
                "scope_value": scope["scope_value"],
                "external_ref_hash": scope["external_ref_hash"],
                "display_label": scope["display_label"],
                "created_obs_id": scope["created_obs_id"],
            },
        )
        connection.execute(
            sa.text("DELETE FROM ansich_entities WHERE entity_id = :entity_id"),
            {"entity_id": old_scope_id},
        )

    if scopes_need_columns:
        with op.batch_alter_table("ansich_scopes") as batch:
            batch.alter_column("scope_value", existing_type=sa.String(256), nullable=True)
            batch.alter_column("external_ref_hash", existing_type=sa.String(64), nullable=False)
            batch.alter_column("display_label", existing_type=sa.String(256), nullable=False)
            batch.alter_column("created_obs_id", existing_type=sa.String(36), nullable=False)
            batch.create_foreign_key(
                "fk_ansich_scope_parent",
                "ansich_scopes",
                ["parent_scope_id"],
                ["entity_id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_ansich_scope_created_obs",
                "ansich_observations",
                ["created_obs_id"],
                ["obs_id"],
                ondelete="RESTRICT",
            )
            batch.create_unique_constraint(
                "uq_ansich_scope_kind_external_ref_hash",
                ["scope_kind", "external_ref_hash"],
            )
            batch.create_index("ix_ansich_scopes_parent", ["parent_scope_id"])

    if relations_need_columns:
        with op.batch_alter_table("ansich_relations") as batch:
            batch.add_column(sa.Column("relation_role", sa.String(32)))
            batch.add_column(sa.Column("inherited_from_task_id", sa.String(36)))
            batch.create_foreign_key(
                "fk_ansich_relation_inherited_task",
                "ansich_tasks",
                ["inherited_from_task_id"],
                ["entity_id"],
                ondelete="RESTRICT",
            )

    connection.execute(
        sa.text(
            """
            UPDATE ansich_relations
            SET relation_role = CASE (
                SELECT scope_kind
                FROM ansich_scopes
                WHERE ansich_scopes.entity_id = ansich_relations.object_id
            )
                WHEN 'owner' THEN 'owner'
                WHEN 'thread' THEN 'conversation'
                WHEN 'workspace' THEN 'execution_workspace'
                WHEN 'sandbox' THEN 'sandbox_boundary'
                WHEN 'authorization' THEN 'auth_context'
                WHEN 'external_origin' THEN 'trigger_origin'
            END
            WHERE predicate = 'within_scope'
            """
        )
    )

    _create_table(
        "ansich_authorization_snapshots",
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("tool_call_id", sa.String(36), nullable=False),
        sa.Column("policy_id", sa.String(256), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("details_available", sa.Boolean(), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_obs_id", sa.String(36), nullable=False),
        sa.Column("payload_id", sa.String(36)),
        sa.CheckConstraint(
            "decision IN ('allowed', 'denied', 'unknown')",
            name="ck_ansich_authorization_decision",
        ),
        sa.ForeignKeyConstraint(["snapshot_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_call_id"], ["ansich_tool_calls.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluated_obs_id"], ["ansich_observations.obs_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payload_id"], ["ansich_payloads.payload_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    _create_index(
        "ix_ansich_authorization_tool_evaluated",
        "ansich_authorization_snapshots",
        ["tool_call_id", "evaluated_obs_id"],
    )
    _create_index(
        "ix_ansich_authorization_decision_policy",
        "ansich_authorization_snapshots",
        ["decision", "policy_id"],
    )
    _create_table(
        "ansich_authorization_scopes",
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("scope_role", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=False),
        sa.CheckConstraint(
            "scope_role IN ('principal', 'resource')",
            name="ck_ansich_authorization_scope_role",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["ansich_authorization_snapshots.snapshot_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["scope_id"], ["ansich_scopes.entity_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("snapshot_id", "scope_role", "ordinal"),
        sa.UniqueConstraint(
            "snapshot_id",
            "scope_role",
            "scope_id",
            name="uq_ansich_authorization_scope_membership",
        ),
    )
    _create_index(
        "ix_ansich_authorization_scopes_scope",
        "ansich_authorization_scopes",
        ["scope_id", "snapshot_id"],
    )
    _create_table(
        "ansich_authorization_permissions",
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("resource", sa.String(512), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("scope_id", sa.String(36)),
        sa.Column("effect", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["ansich_authorization_snapshots.snapshot_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["scope_id"], ["ansich_scopes.entity_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("snapshot_id", "ordinal"),
    )
    _create_table(
        "ansich_tool_call_authorizations",
        sa.Column("tool_call_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("relation_obs_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["tool_call_id"], ["ansich_tool_calls.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["ansich_authorization_snapshots.snapshot_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["relation_obs_id"], ["ansich_observations.obs_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("tool_call_id", "snapshot_id"),
    )
    _create_table(
        "ansich_tool_effects",
        sa.Column("effect_id", sa.String(36), nullable=False),
        sa.Column("tool_call_id", sa.String(36), nullable=False),
        sa.Column("effect_class", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(36)),
        sa.Column("target_hash", sa.String(64)),
        sa.Column("target_preview", sa.String(512)),
        sa.Column("fidelity_class", sa.String(16), nullable=False),
        sa.Column("source_obs_id", sa.String(36), nullable=False),
        sa.Column("result_metadata_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "phase IN ('potential', 'intended', 'observed')",
            name="ck_ansich_tool_effect_phase",
        ),
        sa.CheckConstraint(
            "effect_class IN ('filesystem_read', 'filesystem_write', 'filesystem_delete', 'process_execute', 'network_read', 'external_write', 'permission_change', 'child_task_spawn', 'unknown')",
            name="ck_ansich_tool_effect_class",
        ),
        sa.ForeignKeyConstraint(["effect_id"], ["ansich_entities.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_call_id"], ["ansich_tool_calls.entity_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scope_id"], ["ansich_scopes.entity_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_obs_id"], ["ansich_observations.obs_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("effect_id"),
    )
    _create_index(
        "ix_ansich_tool_effect_class_phase_scope",
        "ansich_tool_effects",
        ["effect_class", "phase", "scope_id"],
    )
    _create_index(
        "ix_ansich_tool_effect_scope_tool",
        "ansich_tool_effects",
        ["scope_id", "tool_call_id"],
    )
    _create_table(
        "ansich_scope_conclusions",
        sa.Column("assertion_id", sa.String(36), nullable=False),
        sa.Column("tool_call_id", sa.String(36), nullable=False),
        sa.Column("conclusion_kind", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "conclusion_kind IN ('policy_denial', 'attempted_scope_violation', 'realized_scope_violation', 'unverified_effect')",
            name="ck_ansich_scope_conclusion_kind",
        ),
        sa.ForeignKeyConstraint(
            ["assertion_id"],
            ["ansich_belief_assertions.assertion_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tool_call_id"], ["ansich_tool_calls.entity_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assertion_id"),
    )
    _create_index(
        "ix_ansich_scope_conclusions_tool_kind",
        "ansich_scope_conclusions",
        ["tool_call_id", "conclusion_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_ansich_scope_conclusions_tool_kind", table_name="ansich_scope_conclusions")
    op.drop_table("ansich_scope_conclusions")
    op.drop_index("ix_ansich_tool_effect_scope_tool", table_name="ansich_tool_effects")
    op.drop_index("ix_ansich_tool_effect_class_phase_scope", table_name="ansich_tool_effects")
    op.drop_table("ansich_tool_effects")
    op.drop_table("ansich_tool_call_authorizations")
    op.drop_table("ansich_authorization_permissions")
    op.drop_index(
        "ix_ansich_authorization_scopes_scope",
        table_name="ansich_authorization_scopes",
    )
    op.drop_table("ansich_authorization_scopes")
    op.drop_index(
        "ix_ansich_authorization_decision_policy",
        table_name="ansich_authorization_snapshots",
    )
    op.drop_index(
        "ix_ansich_authorization_tool_evaluated",
        table_name="ansich_authorization_snapshots",
    )
    op.drop_table("ansich_authorization_snapshots")

    with op.batch_alter_table("ansich_relations") as batch:
        batch.drop_constraint("fk_ansich_relation_inherited_task", type_="foreignkey")
        batch.drop_column("inherited_from_task_id")
        batch.drop_column("relation_role")

    op.execute(
        sa.text(
            """
            UPDATE ansich_scopes
            SET scope_value = external_ref_hash
            WHERE scope_value IS NULL
            """
        )
    )
    with op.batch_alter_table("ansich_scopes") as batch:
        batch.drop_index("ix_ansich_scopes_parent")
        batch.drop_constraint("uq_ansich_scope_kind_external_ref_hash", type_="unique")
        batch.drop_constraint("fk_ansich_scope_created_obs", type_="foreignkey")
        batch.drop_constraint("fk_ansich_scope_parent", type_="foreignkey")
        batch.alter_column("scope_value", existing_type=sa.String(256), nullable=False)
        batch.drop_column("created_obs_id")
        batch.drop_column("parent_scope_id")
        batch.drop_column("display_label")
        batch.drop_column("external_ref_hash")
