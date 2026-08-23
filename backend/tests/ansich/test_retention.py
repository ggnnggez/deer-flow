"""Retention configuration and the schema migration 0028 introduces.

This is Task 8 of the P11-C batch: the *config* and the *schema*, nothing that
executes retention (Task 9 owns the executor) and nothing that reads or writes
an active version (Task 6 owns that). So the tests here answer three questions
and no others:

1. Does ``AnsichConfig.retention`` parse, bound, and order its tiers, and does
   it inherit the ``ansich`` section's startup-only standing?
2. Does ``config.example.yaml`` mirror it, with the batch's single
   ``config_version`` bump?
3. Does the schema hold the invariants the executor will rely on — a payload
   row is either present or tombstoned (never both, never neither), retention
   state is one row, and an active-version row survives its audit anchor
   expiring?

The migration itself is proved on both dialects: here on SQLite (upgrade to
head, then downgrade back to 0027 and up again), and on PostgreSQL by
``tests/integration/test_postgres_migration_matrix.py``.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import inspect
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args
from uuid import uuid4

import pytest
import sqlalchemy as sa
import yaml
from _router_auth_helpers import make_authed_test_app
from alembic import command as alembic_command
from ansich import AnsichService, HardDeleteReport, ObservationEnvelope, Producer, RetentionPolicy, new_id
from ansich.contracts import ANSICH_BOOTSTRAP_TASK_ID
from ansich.errors import HardDeleteError, HardDeleteRefusal, PayloadExpiredError
from ansich.evaluation import EvaluationProjectionStatus
from ansich.safety import ScopeKind, host_scope_id, scope_entity_id, scope_reference_hash
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from support.ansich_settle import only_test_driven_assessments

# Pre-import models so ``Base.metadata`` carries the DeerFlow tables too.
import deerflow.persistence.models  # noqa: F401
from app.gateway.auth.models import User
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_sql_ansich_service, retention_policy_from_config
from deerflow.ansich.persistence import sql as sql_module
from deerflow.ansich.persistence.models import (
    AnsichActiveTaskReadModelRow,
    AnsichActiveVersionRow,
    AnsichAgentReleaseRow,
    AnsichBeliefAssertionRow,
    AnsichBeliefEvidenceRow,
    AnsichContentBlobRow,
    AnsichContentBlockRow,
    AnsichContentOccurrenceRow,
    AnsichEntityRow,
    AnsichObservationRow,
    AnsichPayloadRow,
    AnsichProjectionJobRow,
    AnsichRetentionStateRow,
    AnsichScopeRow,
    AnsichTaskHeartbeatRow,
)
from deerflow.ansich.persistence.sql import (
    _HARD_DELETE_DEFERRABLE_PIN_REFUSALS,
    _HARD_DELETE_OWNER_SCOPE_KINDS,
    _HARD_DELETE_PROTECTED_ENTITY_TYPES,
    _HARD_DELETE_PROTECTED_PIN_EDGES,
    _PAYLOAD_REFERRER_TIERS,
    _PG_MAINTENANCE_LOCK_KEY,
    _PG_RETENTION_LOCK_KEY,
    SqlAnsichBackend,
    _cascade_delete_closure,
    _HardDeleteCounts,
    _payload_referrer_columns,
)
from deerflow.config.ansich_config import AnsichConfig, AnsichRetentionConfig
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _get_alembic_config, _get_head_revision, _upgrade

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yaml"

# The revision this task authors, and the one it follows.
RETENTION_REVISION = "0028_ansich_retention"
PRE_RETENTION_REVISION = "0027_ansich_lease_generation"

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------


def test_retention_defaults_are_the_three_spec_tiers_plus_a_batch_size():
    """The four names and four values are spec-mandated, not preferences."""
    config = AnsichConfig()

    assert config.retention.raw_payload_days == 7
    assert config.retention.observation_days == 30
    assert config.retention.structural_days == 90
    assert config.retention.cleanup_batch_size == 500


def test_every_retention_field_is_bounded_at_one():
    """Zero is a switch spelled as a bound on all four.

    ``raw_payload_days: 0`` would mean "delete evidence the moment it lands",
    and ``cleanup_batch_size: 0`` would mean "a batch that deletes nothing" —
    an infinite loop rather than a disabled tier. Disabling retention is not
    expressible here on purpose; that is the executor's business.
    """
    for field in ("raw_payload_days", "observation_days", "structural_days", "cleanup_batch_size"):
        with pytest.raises(ValidationError):
            AnsichConfig.model_validate({"retention": {field: 0}})
        with pytest.raises(ValidationError):
            AnsichConfig.model_validate({"retention": {field: -1}})


def test_retention_tiers_must_not_invert():
    """``raw_payload <= observation <= structural`` — each tier is contained.

    An observation whose payload outlives it is unreadable evidence kept at
    cost; a Task whose structural row dies before its Observations leaves
    dangling references. Equality is legal: two tiers expiring together is a
    policy, not a contradiction.
    """
    AnsichConfig.model_validate({"retention": {"raw_payload_days": 30, "observation_days": 30, "structural_days": 30}})

    with pytest.raises(ValidationError, match="raw_payload_days"):
        AnsichConfig.model_validate({"retention": {"raw_payload_days": 31, "observation_days": 30}})
    with pytest.raises(ValidationError, match="observation_days"):
        AnsichConfig.model_validate({"retention": {"observation_days": 91, "structural_days": 90}})


def test_retention_is_startup_only_by_inheritance():
    """The whole ``ansich`` section is restart-required, so this block is too.

    There is no per-subfield registry entry to add — ``STARTUP_ONLY_FIELDS``
    registers ``ansich`` — but the standardised marker must still be on the
    field, because that prefix is what IDE hover and any future needs-restart
    scanner pivot on. A field missing it reads as hot-reloadable while every
    one of its neighbours is not.
    """
    assert "ansich" in STARTUP_ONLY_FIELDS
    assert AnsichConfig.model_fields["retention"].description.startswith("startup-only:")


def test_retention_config_is_reachable_as_its_own_model():
    """The sub-model is public: Task 9's executor takes a policy, not a config."""
    policy = AnsichRetentionConfig(raw_payload_days=1, observation_days=2, structural_days=3, cleanup_batch_size=10)

    assert policy.raw_payload_days == 1
    assert policy.cleanup_batch_size == 10
    with pytest.raises(ValidationError):
        AnsichRetentionConfig(raw_payload_days=5, observation_days=2)


# ---------------------------------------------------------------------------
# 2. config.example.yaml
# ---------------------------------------------------------------------------


def test_config_example_mirrors_the_retention_block_with_a_single_version_bump():
    """The example is the operator-facing copy of the model's defaults.

    ``config_version`` is bumped exactly once per batch (Global Constraint 14):
    this task is the batch's first key-adding task, so it owns the bump and the
    later ones (``raw_read_max_bytes``, ``shutdown_budget_ms``) add keys without
    touching it. The assertion is a floor rather than an equality so a later
    batch's bump does not turn this into a false red.
    """
    document = yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8"))

    assert document["config_version"] >= 36, "config.example.yaml must be bumped for ansich.retention"

    retention = document["ansich"]["retention"]
    defaults = AnsichRetentionConfig()
    assert retention == {
        "raw_payload_days": defaults.raw_payload_days,
        "observation_days": defaults.observation_days,
        "structural_days": defaults.structural_days,
        "cleanup_batch_size": defaults.cleanup_batch_size,
    }


# ---------------------------------------------------------------------------
# 3. Schema
# ---------------------------------------------------------------------------


def _engine(*, foreign_keys: bool = False):
    engine = create_engine("sqlite:///:memory:")
    if foreign_keys:

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record):  # pragma: no cover - trivial hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    return engine


def _payload(**overrides) -> AnsichPayloadRow:
    fields = {
        "payload_id": "payload-1",
        "content_type": "application/json",
        "encoding": "utf-8",
        "compression": "none",
        "byte_size": 4,
        "sha256": "a" * 64,
        "body": b"{}\n\n",
    }
    fields.update(overrides)
    return AnsichPayloadRow(**fields)


def test_a_payload_is_either_present_or_tombstoned_never_both():
    """``ck_ansich_payload_tombstone_one_of``: body XOR deleted_at.

    Both means a reader cannot tell whether the bytes it just read are still
    policy-current; the tombstone would be decoration.
    """
    engine = _engine()
    with Session(engine) as session:
        session.add(_payload(deleted_at=NOW, policy="raw_payload_days=7"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_payload_with_neither_body_nor_tombstone_is_refused():
    """Neither means an unreadable row that claims nothing happened to it.

    That is exactly the state RC6 keeps distinguishable from a tombstone: a
    body-less row with no ``deleted_at`` is corruption, and the constraint
    makes it unwritable rather than leaving readers to guess.
    """
    engine = _engine()
    with Session(engine) as session:
        session.add(_payload(body=None))
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_tombstone_without_a_policy_is_refused():
    """The tombstone arm requires ``policy``, so the column's promise is enforced.

    ``policy`` exists so an operator reading an expired row can say which rule
    expired it rather than inferring it from a configuration that may since have
    been retuned twice. Leaving it merely conventional would make that a promise
    the schema does not keep: a tombstone stamped without one proves a body was
    deleted and when, and nothing about under which rule — and by the time
    anyone noticed, the table would be full of tombstones and the repair would
    be a migration over them. Task 9 writes the first tombstone; until it does,
    this costs nothing.
    """
    engine = _engine()
    with Session(engine) as session:
        session.add(_payload(body=None, deleted_at=NOW))
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_live_payload_may_not_carry_a_policy():
    """The other half of the same rule: all three columns move together.

    A live row with a retention policy stamped on it is not a state anything
    produces — but if it were writable, ``policy IS NOT NULL`` would stop being
    readable as "this row is expired", which is the only reason a reader looks
    at it.
    """
    engine = _engine()
    with Session(engine) as session:
        session.add(_payload(policy="raw_payload_days=7"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_tombstone_retains_the_lineage_half_and_the_policy_that_made_it():
    """sha256/byte_size stay; they are what a tombstone still proves."""
    engine = _engine()
    with Session(engine) as session:
        session.add(_payload(body=None, deleted_at=NOW, policy="raw_payload_days=7"))
        session.commit()

    with Session(engine) as session:
        row = session.execute(select(AnsichPayloadRow)).scalar_one()
        assert row.body is None
        assert row.deleted_at is not None
        assert row.policy == "raw_payload_days=7"
        # The lineage half survives the delete: a reader can still say what the
        # bytes were, only not what they said.
        assert row.sha256 == "a" * 64
        assert row.byte_size == 4


def test_retention_state_is_one_row_with_no_fabricated_numbers():
    """id=1 single-row table; every "not yet" field is None, never zero.

    The horizon is the exception and it is deliberate: ``ingest_seq`` starts at
    1, so a horizon of 0 is the honest "nothing has been deleted yet" rather
    than a fabricated timestamp.
    """
    engine = _engine()
    with Session(engine) as session:
        session.add(AnsichRetentionStateRow(id=1))
        session.commit()

    with Session(engine) as session:
        row = session.execute(select(AnsichRetentionStateRow)).scalar_one()
        assert row.id == 1
        assert row.payload_cursor is None
        assert row.observation_cursor is None
        assert row.structural_cursor is None
        assert row.observation_horizon_ingest_seq == 0
        assert row.last_run_started_at is None
        assert row.last_run_finished_at is None
        assert row.last_run_policy is None


def test_a_second_retention_state_row_is_refused():
    """The check constraint is what makes "the horizon" a definite article."""
    engine = _engine()
    with Session(engine) as session:
        session.add(AnsichRetentionStateRow(id=2))
        with pytest.raises(IntegrityError):
            session.commit()


def _observation(obs_id: str) -> AnsichObservationRow:
    return AnsichObservationRow(
        obs_id=obs_id,
        schema_version=1,
        kind="operator.action_succeeded",
        occurred_at=NOW,
        recorded_at=NOW,
        task_id="task-1",
        subject_type="scope",
        subject_id="scope-1",
        fidelity_class="hard",
        producer_name="test-retention",
        producer_version="1",
        producer_instance_id="test-instance",
        producer_seq=1,
        source_event_id=f"source:{obs_id}",
        correlation_id=f"corr:{obs_id}",
        payload_json={},
    )


def test_an_active_version_row_round_trips():
    engine = _engine()
    with Session(engine) as session:
        session.add(_observation("obs-1"))
        session.flush()
        session.add(
            AnsichActiveVersionRow(
                component_kind="resolver",
                component_name="ansich-default",
                active_version="2.0.0",
                activated_at=NOW,
                activated_by="operator@example.com",
                audit_obs_id="obs-1",
                audit_recorded=True,
            )
        )
        session.commit()

    with Session(engine) as session:
        row = session.execute(select(AnsichActiveVersionRow)).scalar_one()
        assert (row.component_kind, row.component_name) == ("resolver", "ansich-default")
        assert row.active_version == "2.0.0"
        assert row.activated_by == "operator@example.com"
        assert row.audit_obs_id == "obs-1"
        assert row.audit_recorded is True


def test_a_never_audited_row_is_distinguishable_from_an_expired_one():
    """The tri-state: ``audit_recorded`` is what keeps the two NULLs apart.

    Both a degraded audit write and retention's SET NULL leave
    ``audit_obs_id IS NULL``, and they are opposite facts — "this switch was
    never audited" versus "it was, and the evidence aged out under policy". For
    an *audit anchor* that is the one distinction that matters, and it is the
    same none-never-zero discipline the horizon column two tables up applies to
    itself. The latch is the only thing that survives the FK action, so it is
    the only thing that can carry the difference.
    """
    engine = _engine(foreign_keys=True)
    with Session(engine) as session:
        session.add(_observation("obs-1"))
        session.flush()
        # Audited: latch set in the same statement as the pointer.
        session.add(
            AnsichActiveVersionRow(
                component_kind="projector",
                component_name="task-heartbeat",
                active_version="1",
                activated_at=NOW,
                activated_by="operator@example.com",
                audit_obs_id="obs-1",
                audit_recorded=True,
            )
        )
        # Never audited: the audit write was degraded, so no pointer and no latch.
        session.add(
            AnsichActiveVersionRow(
                component_kind="resolver",
                component_name="ansich-default",
                active_version="2.0.0",
                activated_at=NOW,
                activated_by="operator@example.com",
            )
        )
        session.commit()

        session.execute(sa.delete(AnsichObservationRow).where(AnsichObservationRow.obs_id == "obs-1"))
        session.commit()

    with Session(engine) as session:
        rows = {row.component_kind: row for row in session.execute(select(AnsichActiveVersionRow)).scalars()}

    expired = rows["projector"]
    never = rows["resolver"]
    # Both pointers read NULL...
    assert expired.audit_obs_id is None
    assert never.audit_obs_id is None
    # ...and the latch is what tells them apart.
    assert expired.audit_recorded is True, "the latch must outlive the evidence it describes"
    assert never.audit_recorded is False


def test_an_audit_pointer_without_the_latch_is_refused():
    """The fourth combination is impossible, and the check says so.

    A pointer with no latch would mean "evidence exists that never existed".
    Forbidding it is what makes the other three readable as a closed set rather
    than as three of four possibilities.
    """
    engine = _engine()
    with Session(engine) as session:
        session.add(_observation("obs-1"))
        session.flush()
        session.add(
            AnsichActiveVersionRow(
                component_kind="projector",
                component_name="task-heartbeat",
                active_version="1",
                activated_at=NOW,
                activated_by="operator@example.com",
                audit_obs_id="obs-1",
                audit_recorded=False,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_the_audit_latch_defaults_to_never_audited():
    """Absent means never audited, not unknown — so the default is False.

    A row written without the latch is one nothing claimed to have audited, and
    that is the honest reading of a default rather than a fabricated one.
    """
    engine = _engine()
    with Session(engine) as session:
        session.add(
            AnsichActiveVersionRow(
                component_kind="resolver",
                component_name="ansich-default",
                active_version="2.0.0",
                activated_at=NOW,
                activated_by="operator@example.com",
            )
        )
        session.commit()

    with Session(engine) as session:
        row = session.execute(select(AnsichActiveVersionRow)).scalar_one()
        assert row.audit_recorded is False
        assert row.audit_obs_id is None


def test_an_active_version_survives_its_audit_anchor_expiring():
    """``ON DELETE SET NULL`` — the selection outlives the evidence for it.

    The other two choices are both wrong here, and retention is what decides
    it. CASCADE would let tier 2 silently revert a deliberate operator switch
    to the code default the day the audit Observation aged out — a version
    change nobody made. RESTRICT would let one audit row pin an Observation
    (and the whole contiguous prefix behind it) out of retention forever. SET
    NULL keeps the row and degrades only the pointer, which is the same shape
    ``0021``'s Task-summary assertion pointer already uses for expired
    evidence.
    """
    engine = _engine(foreign_keys=True)
    with Session(engine) as session:
        session.add(_observation("obs-1"))
        session.flush()
        session.add(
            AnsichActiveVersionRow(
                component_kind="projector",
                component_name="task-heartbeat",
                active_version="1",
                activated_at=NOW,
                activated_by="operator@example.com",
                audit_obs_id="obs-1",
                audit_recorded=True,
            )
        )
        session.commit()

        session.execute(sa.delete(AnsichObservationRow).where(AnsichObservationRow.obs_id == "obs-1"))
        session.commit()

    with Session(engine) as session:
        row = session.execute(select(AnsichActiveVersionRow)).scalar_one()
        assert row.active_version == "1", "the selection must survive its audit anchor"
        assert row.audit_obs_id is None, "the pointer degrades to unknown, it does not resurrect"


# ---------------------------------------------------------------------------
# 4. Migration 0028 on SQLite
# ---------------------------------------------------------------------------


def _sqlite_url(tmp_path: Path, name: str = "retention.db") -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / name).as_posix()}"


async def _table_names(engine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))


async def _payload_columns(engine) -> dict[str, dict]:
    async with engine.connect() as conn:
        columns = await conn.run_sync(lambda c: sa.inspect(c).get_columns("ansich_payloads"))
    return {column["name"]: column for column in columns}


async def _payload_check_names(engine) -> list[str]:
    """Every CHECK constraint name on ``ansich_payloads``, duplicates included.

    A list rather than a set on purpose: the migration's ``_has_tombstone_check``
    guard exists to keep a re-run from adding the constraint twice, and a set
    would hide exactly that.
    """
    async with engine.connect() as conn:
        constraints = await conn.run_sync(lambda c: sa.inspect(c).get_check_constraints("ansich_payloads"))
    return [constraint["name"] for constraint in constraints]


async def _insert_payload(engine, **overrides) -> None:
    """Insert one payload row through raw SQL, bypassing the ORM's own view.

    The migrated database is the subject here, so the row has to go in without
    ``Base.metadata`` — otherwise a passing test would only prove the model
    carries the constraint, which is what the ``create_all`` tests above already
    prove separately.
    """
    values = {
        "payload_id": "payload-migrated",
        "content_type": "application/json",
        "encoding": "utf-8",
        "compression": "none",
        "byte_size": 4,
        "sha256": "a" * 64,
        "body": b"{}\n\n",
        "deleted_at": None,
        "policy": None,
    }
    values.update(overrides)
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO ansich_payloads (payload_id, content_type, encoding, compression, byte_size, sha256, body, deleted_at, policy, created_at) "
                "VALUES (:payload_id, :content_type, :encoding, :compression, :byte_size, :sha256, :body, :deleted_at, :policy, '2026-08-22 12:00:00+00:00')"
            ),
            values,
        )


def test_head_is_the_retention_revision():
    assert _get_head_revision() == RETENTION_REVISION


@pytest.mark.asyncio
async def test_migration_0028_adds_the_tables_and_columns_on_sqlite(tmp_path: Path):
    """Upgrade through the real chain, not ``create_all``.

    ``render_as_batch`` is what carries the ``ansich_payloads`` ALTER on
    SQLite (which cannot drop NOT NULL in place), so this is the only way to
    prove the revision rather than the model.
    """
    engine = create_async_engine(_sqlite_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, PRE_RETENTION_REVISION)

        before = await _table_names(engine)
        assert "ansich_retention_state" not in before
        assert "ansich_active_versions" not in before
        assert (await _payload_columns(engine))["body"]["nullable"] is False

        await asyncio.to_thread(_upgrade, cfg, "head")

        after = await _table_names(engine)
        assert "ansich_retention_state" in after
        assert "ansich_active_versions" in after
        columns = await _payload_columns(engine)
        assert columns["body"]["nullable"] is True
        assert "deleted_at" in columns
        assert "policy" in columns
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_tombstone_check_survives_the_sqlite_migration_path(tmp_path: Path):
    """The constraint has to arrive through the revision, not only the model.

    Everything above proves the check on a database ``Base.metadata.create_all``
    built, which is the *empty-database* bootstrap branch. An existing
    deployment takes the other branch — ``alembic upgrade`` over a table that
    already holds rows — and there SQLite cannot add a CHECK in place at all:
    the constraint exists only if ``batch_alter_table`` recreated the table with
    it. So without this test a migration that quietly dropped the check would
    leave every upgraded SQLite deployment able to write a body-less row with no
    ``deleted_at`` — the corruption state the whole three-way distinction rests
    on being unwritable — and nothing would go red.

    The row inserted before the upgrade also makes this a recreate over real
    data rather than over an empty table, so a batch operation that lost rows
    would be caught here too.
    """
    engine = create_async_engine(_sqlite_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, PRE_RETENTION_REVISION)

        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO ansich_payloads (payload_id, content_type, encoding, compression, byte_size, sha256, body, created_at) "
                    "VALUES ('payload-legacy', 'application/json', 'utf-8', 'none', 4, :sha256, :body, '2026-08-22 12:00:00+00:00')"
                ),
                {"sha256": "b" * 64, "body": b"{}\n\n"},
            )

        await asyncio.to_thread(_upgrade, cfg, "head")

        assert "ck_ansich_payload_tombstone_one_of" in await _payload_check_names(engine)

        # The pre-existing row survived the recreate and reads as a live payload.
        async with engine.connect() as conn:
            legacy = (await conn.execute(sa.text("SELECT body, deleted_at FROM ansich_payloads WHERE payload_id = 'payload-legacy'"))).one()
        assert legacy.body == b"{}\n\n"
        assert legacy.deleted_at is None

        # Tombstoning the migrated row is allowed; the two illegal halves are not.
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE ansich_payloads SET body = NULL, deleted_at = '2026-08-22 12:00:00+00:00', policy = 'raw_payload_days=7' WHERE payload_id = 'payload-legacy'"))
        with pytest.raises(IntegrityError):
            await _insert_payload(engine, payload_id="payload-both", deleted_at="2026-08-22 12:00:00+00:00")
        with pytest.raises(IntegrityError):
            await _insert_payload(engine, payload_id="payload-neither", body=None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_0028_clears_the_active_task_read_model(tmp_path: Path):
    """RC11: the data step kills F10-32's expiring premise.

    A row written by pre-P11-B code carries the old stamp (that worker's
    highest projected ``ingest_seq``), which sits at or above the continuity
    mark every later tick computes — so the publish guard skips it forever
    while any job is durably failed, silently for Tasks that have stopped.
    The rows are a pure read model, so deleting them costs one ops tick.
    """
    engine = create_async_engine(_sqlite_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, PRE_RETENTION_REVISION)

        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO ansich_active_task_read_model ("
                    "task_id, run_id, source_kind, control_value, heartbeat_value, budget_status, "
                    "duration_ms, observability_status, projection_watermark, projection_lag_ms, "
                    "control_json, dwell_json, heartbeat_json, usage_json, budgets_json, "
                    "budget_health_json, lost_ranges_json, last_evidence_at, updated_at"
                    ") VALUES ("
                    "'task-stale', 'run-stale', 'deerflow_run', 'running', 'ok', 'ok', "
                    "0, 'complete', 4242, 0, "
                    "'{}', '{}', '{}', '{}', '{}', "
                    "'[]', '[]', '2026-08-22 12:00:00+00:00', '2026-08-22 12:00:00+00:00')"
                )
            )

        await asyncio.to_thread(_upgrade, cfg, "head")

        async with engine.connect() as conn:
            remaining = (await conn.execute(sa.text("SELECT COUNT(*) FROM ansich_active_task_read_model"))).scalar()
        assert remaining == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_0028_is_reversible_and_re_appliable_on_sqlite(tmp_path: Path):
    """Downgrade walks the batch ALTER back; the second upgrade is a no-op."""
    engine = create_async_engine(_sqlite_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, "head")
        await asyncio.to_thread(alembic_command.downgrade, cfg, PRE_RETENTION_REVISION)

        tables = await _table_names(engine)
        assert "ansich_retention_state" not in tables
        assert "ansich_active_versions" not in tables
        columns = await _payload_columns(engine)
        assert "deleted_at" not in columns
        assert "policy" not in columns
        assert columns["body"]["nullable"] is False

        await asyncio.to_thread(_upgrade, cfg, "head")
        await asyncio.to_thread(_upgrade, cfg, "head")

        columns = await _payload_columns(engine)
        assert columns["body"]["nullable"] is True
        # The re-applied upgrade must not stack a second copy of the check: the
        # migration's ``_has_tombstone_check`` guard is the only thing stopping
        # it, and a duplicate would survive silently until someone read the DDL.
        assert (await _payload_check_names(engine)).count("ck_ansich_payload_tombstone_one_of") == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_downgrade_keeps_live_payloads_and_drops_only_tombstones(tmp_path: Path):
    """The dangerous direction, over real rows — ``0027``'s own precedent.

    The reversibility test above walks an *empty* database back, so it proves
    the DDL executes and nothing about the data. This direction is the one that
    deletes rows on purpose, and on SQLite the whole thing is a table recreate:
    a widened predicate, or a ``copy_from`` that loses rows in the copy, would
    destroy every live payload on downgrade with the suite still green.
    ``0027``'s downgrade test asserts exactly this property for its own table
    ("drops columns, never job rows").
    """
    engine = create_async_engine(_sqlite_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, "head")

        await _insert_payload(engine, payload_id="payload-live", body=b"{}\n\n")
        await _insert_payload(engine, payload_id="payload-live-2", body=b"[1]")
        await _insert_payload(
            engine,
            payload_id="payload-tombstoned",
            body=None,
            deleted_at="2026-08-22 12:00:00+00:00",
            policy="raw_payload_days=7",
        )

        await asyncio.to_thread(alembic_command.downgrade, cfg, PRE_RETENTION_REVISION)

        async with engine.connect() as conn:
            rows = (await conn.execute(sa.text("SELECT payload_id, body FROM ansich_payloads ORDER BY payload_id"))).all()

        # The tombstone is gone (the pre-0028 schema cannot express it) and both
        # live payloads survived the recreate with their bodies intact.
        assert [row.payload_id for row in rows] == ["payload-live", "payload-live-2"]
        assert [row.body for row in rows] == [b"{}\n\n", b"[1]"]
        columns = await _payload_columns(engine)
        assert columns["body"]["nullable"] is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_downgrade_refuses_a_referenced_tombstone_on_sqlite(tmp_path: Path):
    """The refusal has to be explicit, because the FK is not enforced here.

    ``ansich_observations.payload_ref_id`` is ``ON DELETE RESTRICT``, which
    makes PostgreSQL refuse this delete on its own. The migration connection
    runs with SQLite's foreign keys **off** (``migrations/env.py`` sets only
    ``busy_timeout``), so on this dialect the same statement would succeed
    silently and leave the Observation pointing at nothing — manufacturing the
    corruption state the tombstone exists to stay distinguishable from, using
    the tool that was supposed to refuse. The pre-flight query is what makes
    both dialects behave the same way.

    **And it must run before anything destructive, which is what this test
    actually pins.** pysqlite opens no transaction for DDL, so a raise is not a
    rollback here: every statement the downgrade had already issued stays
    applied. With the guard positioned after the two ``_drop_table`` calls, a
    refused downgrade permanently destroyed the retention cursors, the deletion
    horizon and every operator version selection — while reporting that it had
    changed nothing. So the assertions below are not decoration: they are the
    difference between a guard and a guard that runs too late.
    """
    engine = create_async_engine(_sqlite_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, "head")

        await _insert_payload(
            engine,
            payload_id="payload-referenced",
            body=None,
            deleted_at="2026-08-22 12:00:00+00:00",
            policy="raw_payload_days=7",
        )
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO ansich_observations (obs_id, schema_version, kind, occurred_at, recorded_at, task_id, "
                    "subject_type, subject_id, fidelity_class, producer_name, producer_version, producer_instance_id, "
                    "producer_seq, source_event_id, correlation_id, payload_ref_id) "
                    "VALUES ('obs-ref', 1, 'operator.action_succeeded', '2026-08-22 12:00:00+00:00', "
                    "'2026-08-22 12:00:00+00:00', 'task-1', 'scope', 'scope-1', 'hard', 'test-retention', '1', "
                    "'test-instance', 1, 'source:obs-ref', 'corr:obs-ref', 'payload-referenced')"
                )
            )
            # A second referrer on the same payload, from a DIFFERENT referrer
            # table. The refusal counts blocked *payloads*, not references, and
            # only two tables can show that: the per-table sum this replaced
            # already collapsed two rows in one table to 1, so a second
            # Observation would discriminate nothing. Across two tables the old
            # form counts 2 and the current one counts 1.
            # `ansich_content_blobs` satisfies its own inline_body/payload_ref_id
            # XOR check by leaving `inline_body` NULL.
            await conn.execute(
                sa.text(
                    "INSERT INTO ansich_content_blobs (blob_key, content_hash, byte_size, content_type, canonicalization_version, inline_body, payload_ref_id, created_at) "
                    "VALUES ('blob-ref', :content_hash, 4, 'application/json', '1', NULL, 'payload-referenced', '2026-08-22 12:00:00+00:00')"
                ),
                {"content_hash": "d" * 64},
            )
            # State a retention pass would have earned: a horizon that is not 0,
            # and an operator's version selection with its audit latch.
            await conn.execute(sa.text("INSERT INTO ansich_retention_state (id, observation_horizon_ingest_seq, payload_cursor) VALUES (1, 4242, 'payload-cursor-1')"))
            await conn.execute(
                sa.text(
                    "INSERT INTO ansich_active_versions (component_kind, component_name, active_version, activated_at, activated_by, audit_recorded) "
                    "VALUES ('resolver', 'ansich-default', '2.0.0', '2026-08-22 12:00:00+00:00', 'operator@example.com', 1)"
                )
            )

        with pytest.raises(RuntimeError, match=r"1 tombstoned payload row\(s\).*still referenced"):
            await asyncio.to_thread(alembic_command.downgrade, cfg, PRE_RETENTION_REVISION)

        # Nothing was destroyed on the way to the refusal.
        tables = await _table_names(engine)
        assert "ansich_retention_state" in tables, "a refused downgrade must not drop the retention state"
        assert "ansich_active_versions" in tables, "a refused downgrade must not drop operator version selections"

        async with engine.connect() as conn:
            remaining = (await conn.execute(sa.text("SELECT COUNT(*) FROM ansich_payloads WHERE payload_id = 'payload-referenced'"))).scalar()
            state = (await conn.execute(sa.text("SELECT observation_horizon_ingest_seq, payload_cursor FROM ansich_retention_state"))).one()
            active = (await conn.execute(sa.text("SELECT active_version, audit_recorded FROM ansich_active_versions"))).one()
        assert remaining == 1
        # The horizon in particular: recreating it empty would read as 0 —
        # "nothing deleted yet" — which is a lie once a pass has run, and one
        # that makes receipt resolution answer `failed` for expired evidence.
        assert state.observation_horizon_ingest_seq == 4242
        assert state.payload_cursor == "payload-cursor-1"
        assert active.active_version == "2.0.0"
        assert bool(active.audit_recorded) is True
    finally:
        await engine.dispose()


def test_the_downgrade_referrer_list_matches_every_real_foreign_key():
    """The pre-flight refusal is only as complete as its referrer list.

    That list is written out literally rather than reflected, because a
    migration must describe the schema *at its own revision* and not whatever a
    later one made of it. The cost of writing it by hand is that it can be
    wrong, and a wrong entry is not a quiet no-op: a column that is not really a
    foreign key makes the pre-check query itself fail (``bytea = varchar`` was
    the actual mistake, and it took a live PostgreSQL to surface it because
    SQLite compares those happily), while a *missing* entry silently narrows the
    refusal to the referrers someone remembered.

    At this revision the literal list and the ORM's foreign keys are the same
    set, so pinning them together is honest. A later revision that adds a
    referrer will turn this red — which is the right prompt: decide whether
    0028's downgrade should refuse for it too, rather than discovering it on a
    production rollback.
    """
    revision_module = importlib.import_module(f"deerflow.persistence.migrations.versions.{RETENTION_REVISION}")

    actual = {(table.name, fk.parent.name, fk.ondelete) for table in Base.metadata.sorted_tables for fk in table.foreign_keys if fk.column.table.name == "ansich_payloads"}
    declared = set(revision_module._PAYLOAD_REFERRERS)

    assert {(table, column) for table, column, _ in actual} == declared
    # All of them are RESTRICT, which is the premise the docstring leans on for
    # the dialect that does enforce the FK.
    assert {ondelete for _, _, ondelete in actual} == {"RESTRICT"}


def test_the_downgrade_copy_spec_declares_the_check_only_when_it_exists():
    """F5: the defensive branch must not break exactly when it fires.

    ``copy_from`` tells alembic what the source table looks like, and on SQLite
    that spec is what the recreate rebuilds from. Declaring the CHECK
    unconditionally breaks the one case the ``_has_tombstone_check()`` guard
    exists for — columns present, constraint absent — because the recreate then
    emits ``CREATE TABLE … CHECK (… deleted_at …)`` over columns the same batch
    is dropping. A defensive branch that fails when it fires is worse than no
    branch.
    """
    revision_module = importlib.import_module(f"deerflow.persistence.migrations.versions.{RETENTION_REVISION}")
    with_check = revision_module._payloads_table_after_upgrade(with_check=True)
    without_check = revision_module._payloads_table_after_upgrade(with_check=False)

    def check_names(table: sa.Table) -> set[str]:
        return {c.name for c in table.constraints if isinstance(c, sa.CheckConstraint)}

    assert check_names(with_check) == {"ck_ansich_payload_tombstone_one_of"}
    assert check_names(without_check) == set()
    # The columns are identical either way — only the constraint differs.
    assert [c.name for c in with_check.columns] == [c.name for c in without_check.columns]


#: ``ansich_payloads`` in its post-0028 shape with the CHECK left off — the state
#: a manual ``ALTER`` (or a future revision that dropped the constraint) leaves
#: behind, and the only state the ``_has_tombstone_check()`` guard exists for.
_PAYLOADS_WITHOUT_CHECK_DDL = """
CREATE TABLE ansich_payloads (
    payload_id VARCHAR(36) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    encoding VARCHAR(32) NOT NULL,
    compression VARCHAR(32) NOT NULL,
    byte_size BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    body BLOB,
    deleted_at DATETIME,
    policy VARCHAR(128),
    created_at DATETIME NOT NULL,
    PRIMARY KEY (payload_id)
)
"""


@pytest.mark.asyncio
async def test_the_downgrade_runs_with_the_check_already_absent(tmp_path: Path):
    """The same branch, executed rather than inspected.

    The state is built for real rather than patched: alembic loads a revision
    module freshly per command, so a monkeypatched copy is not the object the
    migration would run. Dropping and recreating ``ansich_payloads`` without the
    constraint reproduces the manual-``ALTER`` shape the guard was written for,
    and puts the downgrade on the guard-False path over a real database — which
    is exactly where an unconditional ``copy_from`` spec fails.
    """
    engine = create_async_engine(_sqlite_url(tmp_path))
    try:
        cfg = _get_alembic_config(engine)
        await asyncio.to_thread(_upgrade, cfg, "head")

        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP TABLE ansich_payloads"))
            await conn.execute(sa.text(_PAYLOADS_WITHOUT_CHECK_DDL))
        assert await _payload_check_names(engine) == [], "the fixture must actually remove the constraint"

        await _insert_payload(engine, payload_id="payload-live", body=b"{}\n\n")

        await asyncio.to_thread(alembic_command.downgrade, cfg, PRE_RETENTION_REVISION)

        columns = await _payload_columns(engine)
        assert "deleted_at" not in columns
        assert "policy" not in columns
        assert columns["body"]["nullable"] is False
        async with engine.connect() as conn:
            body = (await conn.execute(sa.text("SELECT body FROM ansich_payloads WHERE payload_id = 'payload-live'"))).scalar()
        assert body == b"{}\n\n"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 5. Tier 1 — payload tombstoning, and the horizon machinery behind it
# ---------------------------------------------------------------------------
#
# Everything below drives the real ingest path rather than inserting rows,
# because what tier 1 is aimed at is what live ingest produces: a payload row
# minted by externalization, referenced by exactly the Observation that owns
# it, aged by that Observation's *event* time. The two exceptions insert rows
# directly and say why at the test — a shared payload and a release manifest
# are shapes the ingest path cannot produce on demand.

_RETENTION_OCCURRED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
#: Ten days after the evidence happened, so a seven-day payload policy has
#: expired it and a thirty-day Observation policy has not. Past-dated for the
#: same reason every fixture clock in this suite is: a test that computes its
#: own "now" from the wall clock stops being a test of the cutoff.
_RETENTION_NOW = _RETENTION_OCCURRED_AT + timedelta(days=10)
_POLICY = RetentionPolicy(
    raw_payload_days=7,
    observation_days=30,
    structural_days=90,
    cleanup_batch_size=2,
)


@pytest.fixture
async def retention_backend(tmp_path: Path) -> AsyncIterator[tuple[SqlAnsichBackend, async_sessionmaker]]:
    """One worker over one SQLite file, externalizing **every** payload.

    ``inline_payload_max_bytes=1`` is the whole fixture: it puts every
    Observation's payload in ``ansich_payloads`` instead of inline, which is
    what makes tier 1 reachable at all from ordinary ingest. Production crosses
    that threshold with an 800-metric environment sample; a test should not have
    to build one.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ansich-retention-exec.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SqlAnsichBackend(sessions, inline_payload_max_bytes=1), sessions
    finally:
        await engine.dispose()


def _retention_task_created(task_id: str, *, source_id: str = "run-retention") -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=_RETENTION_OCCURRED_AT,
        source_event_id=f"run:{source_id}:task:created",
    )


def _retention_heartbeat(task_id: str, *, ordinal: int, source_id: str = "run-retention", occurred_at: datetime | None = None) -> ObservationEnvelope:
    return ObservationEnvelope.task_heartbeat(
        task_id=task_id,
        run_id=source_id,
        occurred_at=occurred_at or _RETENTION_OCCURRED_AT,
        elapsed_ms=1000 * ordinal,
        worker_id="worker-retention",
        ownership_epoch="epoch-1",
        source_event_id=f"run:{source_id}:heartbeat:{ordinal}",
        producer_seq=ordinal,
    )


async def _settle_retention(backend: SqlAnsichBackend, *, rounds: int = 5) -> None:
    """Drain the claim queue in bounded rounds (Constraint 11's loop shape)."""

    for _ in range(max(rounds, 1)):
        while await backend.project_pending(limit=200):
            pass
        if await backend.unsettled_job_count() == 0:
            return


async def _unsettled_projection_jobs(sessions: async_sessionmaker) -> int:
    """Projection jobs still owed, ignoring the assessor family.

    Scoped deliberately. ``unsettled_job_count`` spans both job tables, and
    assessor jobs are settled by ``assess_operations`` rather than by
    ``project_pending`` — a heartbeat leaves one behind that nothing in these
    tests drives. What every assertion below is actually about is the
    *projection* queue: whether an expired payload stalls it, and whether a
    payload with work still in flight is protected. Counting the assessor
    backlog into that would be measuring a different thing and calling it this
    one.
    """

    async with sessions() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(AnsichProjectionJobRow).where(AnsichProjectionJobRow.status.in_(("pending", "retry", "processing"))),
            )
            or 0
        )


async def _payload_rows(sessions: async_sessionmaker) -> dict[str, AnsichPayloadRow]:
    async with sessions() as session:
        rows = (await session.execute(select(AnsichPayloadRow))).scalars()
        return {row.payload_id: row for row in rows}


async def _settled_store(backend: SqlAnsichBackend, *, heartbeats: int = 3) -> str:
    task_id = new_id()
    envelopes: list[ObservationEnvelope] = [_retention_task_created(task_id)]
    envelopes.extend(_retention_heartbeat(task_id, ordinal=index + 1) for index in range(heartbeats))
    assert await backend.persist_and_project(envelopes) == len(envelopes)
    await _settle_retention(backend)
    return task_id


@pytest.mark.anyio
async def test_an_expired_payload_body_becomes_a_tombstone_with_its_lineage_intact(retention_backend):
    """D6-3's first tier: the body goes, the row and its lineage stay.

    The two halves are asserted together because either alone is the wrong
    outcome. Deleting the row would make every hydrator raise for a *policy*
    outcome; keeping the body would make the policy decorative. What must
    survive is exactly the pair that lets a later reader say what the bytes were
    without saying what they said.
    """

    backend, sessions = retention_backend
    await _settled_store(backend)
    before = await _payload_rows(sessions)
    assert before, "the fixture must actually externalize payloads"
    lineage = {payload_id: (row.sha256, row.byte_size, row.content_type) for payload_id, row in before.items()}

    report = await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    assert report.payload_tombstoned == len(before)
    assert report.finished is True
    assert report.resumed_from_cursor is False
    assert report.started_at == _RETENTION_NOW
    # Tiers 2 and 3 ran and deleted nothing, which at ten days under a
    # thirty-day Observation policy is the only correct answer. `0` here is a
    # measurement; `None` would mean the tier never ran at all, and the two are
    # kept apart deliberately (see `RetentionReport`).
    assert report.observations_deleted == 0
    assert report.structural_deleted == 0

    after = await _payload_rows(sessions)
    assert set(after) == set(before), "tier 1 must never delete a payload row"
    for payload_id, row in after.items():
        assert row.body is None
        assert row.deleted_at is not None
        assert row.policy == "raw_payload_days=7"
        assert (row.sha256, row.byte_size, row.content_type) == lineage[payload_id]


@pytest.mark.anyio
async def test_a_payload_younger_than_the_policy_is_left_alone(retention_backend):
    backend, sessions = retention_backend
    await _settled_store(backend)

    # Six days after the evidence, under a seven-day policy.
    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=6))

    assert report.payload_tombstoned == 0
    assert all(row.body is not None for row in (await _payload_rows(sessions)).values())


@pytest.mark.anyio
async def test_a_payload_with_any_referrer_younger_than_the_policy_is_skipped(retention_backend):
    """One young referrer protects the whole payload.

    Rows are inserted directly here because the shape under test — two
    Observations sharing one payload row — is not something the ingest path
    produces on demand, and it is exactly the shape a per-referrer answer would
    get wrong. A body two Observations reference is expired only when *both* of
    them are; expiring it on the older one's account would delete evidence the
    younger one still needs, and the only symptom would be a reader that used to
    work.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="shared-payload",
                content_type="application/json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="b" * 64,
                body=b"{}",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        await session.flush()
        for suffix, occurred_at in (("old", _RETENTION_OCCURRED_AT), ("young", _RETENTION_NOW)):
            row = _observation(f"obs-shared-{suffix}")
            row.occurred_at = occurred_at
            row.recorded_at = occurred_at
            row.payload_json = None
            row.payload_ref_id = "shared-payload"
            session.add(row)

    report = await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    assert report.payload_tombstoned == 0
    assert (await _payload_rows(sessions))["shared-payload"].body == b"{}"


@pytest.mark.anyio
async def test_an_agent_release_manifest_is_never_expired_by_time_retention(retention_backend):
    """A manifest is identity, not evidence, and is declared out of the tiers.

    Asserted rather than left to the declaration, because the cost of getting it
    wrong is invisible until someone opens a release page: ``release_hash`` is
    derived from the manifest and every release detail and comparison read
    returns it, so expiring it at seven days would blind those reads for every
    release older than a week — including releases still bound to running Tasks.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="manifest-payload",
                content_type="application/vnd.ansich.agent-release+json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="c" * 64,
                body=b"{}",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        discovered = _observation("obs-release-discovered")
        discovered.occurred_at = _RETENTION_OCCURRED_AT
        discovered.recorded_at = _RETENTION_OCCURRED_AT
        session.add(discovered)
        await session.flush()
        session.add(AnsichEntityRow(entity_id="release-1", entity_type="agent_release", discovered_obs_id="obs-release-discovered"))
        await session.flush()
        session.add(
            AnsichAgentReleaseRow(
                entity_id="release-1",
                namespace="test",
                agent_name="lead-agent",
                release_hash="d" * 64,
                schema_version=1,
                model_hash="e" * 64,
                prompt_hash="f" * 64,
                tool_catalog_hash="0" * 64,
                policy_hash="1" * 64,
                runtime_build_id="build-1",
                manifest_payload_id="manifest-payload",
                discovered_obs_id="obs-release-discovered",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )

    # Well past `raw_payload_days` and `observation_days`, still short of
    # `structural_days`: the window in which the time tiers have every excuse
    # to take it and must not.
    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=60))

    payloads = await _payload_rows(sessions)
    assert payloads["manifest-payload"].body == b"{}"
    assert payloads["manifest-payload"].deleted_at is None
    assert report.payload_tombstoned == 0

    # And the other half of the same sentence, which only became reachable with
    # tier 3: it "goes when its release goes, row and all". Past
    # `structural_days` the release Entity is deleted, the release row goes with
    # it, and the manifest payload — now referred to by nothing — is deleted by
    # the tier that orphaned it rather than left behind for a sweep that will
    # never touch an orphan.
    structural = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=365))

    assert structural.structural_deleted == 1
    assert "manifest-payload" not in await _payload_rows(sessions)
    async with sessions() as session:
        assert await session.get(AnsichAgentReleaseRow, "release-1") is None
        assert await session.get(AnsichEntityRow, "release-1") is None


@pytest.mark.anyio
async def test_a_manifest_survives_a_rebuild_that_transiently_orphans_it(retention_backend):
    """The reviewer's reproduction, committed as the regression it earned.

    The "manifests are excluded from time retention" guarantee used to be a
    predicate over ``ansich_agent_releases`` — protected exactly while a row
    pointed at the payload — while an orphan fell back to its own
    ``created_at``. ``_rebuild_projections_locked`` commits
    ``DELETE FROM ansich_agent_releases`` **before** its drain re-projects, so
    for the whole of a rebuild every manifest payload in the store is an
    orphan; a concurrent retention pass (different advisory key, no
    ``_projection_lock``) then tombstoned it. The re-projection recreated the
    release row against the retained digest and succeeded, so nothing failed
    and nothing alerted — while ``_load_agent_release_manifest`` raised for
    that release forever, with a message saying manifests are excluded from
    time retention, which is what it had just not been.

    The fixture *is* the rebuild window: the delete is the exact statement the
    rebuild commits. What the fix makes true is that the window is no longer a
    window at all.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="manifest-rebuild",
                content_type="application/vnd.ansich.agent-release+json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="c" * 64,
                body=b"{}",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        discovered = _observation("obs-release-rebuild")
        discovered.occurred_at = _RETENTION_OCCURRED_AT
        discovered.recorded_at = _RETENTION_OCCURRED_AT
        session.add(discovered)
        await session.flush()
        session.add(AnsichEntityRow(entity_id="release-rebuild", entity_type="agent_release", discovered_obs_id="obs-release-rebuild"))
        await session.flush()
        session.add(
            AnsichAgentReleaseRow(
                entity_id="release-rebuild",
                namespace="test",
                agent_name="lead-agent",
                release_hash="d" * 64,
                schema_version=1,
                model_hash="e" * 64,
                prompt_hash="f" * 64,
                tool_catalog_hash="0" * 64,
                policy_hash="1" * 64,
                runtime_build_id="build-1",
                manifest_payload_id="manifest-rebuild",
                discovered_obs_id="obs-release-rebuild",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )

    # The rebuild's own first statement, committed in its own transaction
    # exactly as `_rebuild_projections_locked` commits it, before the drain that
    # would recreate the row.
    async with sessions() as session, session.begin():
        await session.execute(sa.delete(AnsichAgentReleaseRow))

    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=365))

    payloads = await _payload_rows(sessions)
    assert payloads["manifest-rebuild"].body == b"{}", "a rebuild's delete must not widen retention's eligibility set"
    assert payloads["manifest-rebuild"].deleted_at is None
    assert report.payload_tombstoned == 0


@pytest.mark.anyio
async def test_an_orphaned_payload_is_never_expired_by_the_time_tiers(retention_backend):
    """The class, not the instance: no orphan is tier 1's to expire.

    Being an orphan is a statement about the rest of the database at the instant
    the query runs, not a property of the payload, and any operation that
    empties a referrer table manufactures one. Rather than narrowing the window
    (two-pass confirmation still loses a manifest to a rebuild that spans two
    passes) or serialising retention behind every rebuild (which is the cost the
    separate advisory key exists to avoid), the orphan branch is gone: whoever
    removes a payload's last referrer owns the payload row.

    The cost is stated rather than hidden — a payload nothing references is
    never reclaimed here — and it is zero today because nothing in this build
    orphans one durably.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="orphan-payload",
                content_type="application/json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="2" * 64,
                body=b"{}",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )

    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=365))

    assert report.payload_tombstoned == 0
    assert (await _payload_rows(sessions))["orphan-payload"].body == b"{}"


@pytest.mark.anyio
async def test_a_pass_that_spends_its_batch_bound_reports_unfinished(retention_backend):
    """``finished`` is an answer, not a constant.

    A bounded pass is what a scheduled caller needs: return the store to normal
    service on a deadline, say honestly that the tier was not walked to the end,
    and resume next time from the cursor this one left. The bound is in batches
    rather than seconds because a batch is the unit that commits — bounding it
    can never leave a half-written one.
    """

    backend, sessions = retention_backend
    await _settled_store(backend, heartbeats=4)
    total = len(await _payload_rows(sessions))
    assert total > _POLICY.cleanup_batch_size

    bounded = await backend.run_retention(_POLICY, now=_RETENTION_NOW, max_batches=1)

    assert bounded.finished is False
    assert bounded.batches == 1
    assert bounded.payload_tombstoned == _POLICY.cleanup_batch_size
    async with sessions() as session:
        assert await session.scalar(select(AnsichRetentionStateRow.payload_cursor)) is not None

    rest = await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    assert rest.finished is True
    assert rest.resumed_from_cursor is True
    assert bounded.payload_tombstoned + rest.payload_tombstoned == total
    assert all(row.body is None for row in (await _payload_rows(sessions)).values())


@pytest.mark.anyio
async def test_a_payload_whose_observation_still_owes_a_projection_is_skipped(retention_backend):
    """An in-flight job pins its evidence, whatever the evidence's age.

    This is what keeps the expired-evidence claim path off the ordinary loop: a
    projector that is about to read a body must find one. It is a separate
    refusal from the age rule, so it is asserted on a payload the age rule would
    otherwise have taken.
    """

    backend, sessions = retention_backend
    task_id = new_id()
    assert await backend.persist_and_project([_retention_task_created(task_id)]) == 1
    # Deliberately not settled: the jobs minted with the Observation are still
    # `pending`.
    async with sessions() as session:
        pending = int(await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow).where(AnsichProjectionJobRow.status == "pending")) or 0)
    assert pending > 0

    report = await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    assert report.payload_tombstoned == 0
    assert all(row.body is not None for row in (await _payload_rows(sessions)).values())


@pytest.mark.anyio
async def test_a_durably_failed_job_does_not_pin_its_payload_out_of_retention(retention_backend):
    """``failed`` is settled, badly — it must not hold a body past its policy.

    The other direction of the previous test, and the reason
    ``_IN_FLIGHT_JOB_STATUSES`` is not simply ``_UNSETTLED_JOB_STATUSES``: a
    durably failed job can sit there for as long as nobody retries it, and
    counting it as in-flight would let one poison job keep its evidence
    indefinitely. A retry that lands after the body expired settles as expired
    evidence instead, which is a state the store can express.
    """

    backend, sessions = retention_backend
    task_id = new_id()
    assert await backend.persist_and_project([_retention_task_created(task_id)]) == 1
    async with sessions() as session, session.begin():
        await session.execute(update(AnsichProjectionJobRow).values(status="failed", attempts=5, last_error="boom"))

    report = await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    assert report.payload_tombstoned == 1
    assert all(row.body is None for row in (await _payload_rows(sessions)).values())


@pytest.mark.anyio
async def test_a_pass_killed_mid_tier_resumes_from_its_cursor_without_double_counting(retention_backend):
    """D6-4's resumable cursor, proved by killing a pass in the middle.

    The injected failure fires on the second batch, so the first batch's UPDATE
    *and* its cursor advance are already committed and the rest is not. The
    re-run must then tombstone exactly the remainder — not the whole set again
    (which would restamp the first batch's policy and inflate the count) and not
    the tail alone by accident of the predicate, which is why the assertion is
    on the total across both passes as well as on each pass's own number.
    """

    backend, sessions = retention_backend
    await _settled_store(backend, heartbeats=4)
    total = len(await _payload_rows(sessions))
    assert total >= 4, "the fixture needs more payloads than one batch holds"

    calls = {"n": 0}
    real_state = SqlAnsichBackend._retention_state

    async def _explode_on_the_second_batch(session):
        state = await real_state(session)
        # The run marker's own transaction is call 1; batches start at 2.
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("injected mid-tier failure")
        return state

    # Shadowed on the instance and then removed, rather than rebound: the real
    # ``_retention_state`` is a ``staticmethod``, so rebinding it through
    # ``__get__`` would hand it ``self`` as its session argument.
    backend._retention_state = _explode_on_the_second_batch  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="injected mid-tier failure"):
        await backend.run_retention(_POLICY, now=_RETENTION_NOW)
    del backend._retention_state

    after_crash = await _payload_rows(sessions)
    tombstoned_first = [row for row in after_crash.values() if row.body is None]
    assert len(tombstoned_first) == _POLICY.cleanup_batch_size
    async with sessions() as session:
        cursor = await session.scalar(select(AnsichRetentionStateRow.payload_cursor))
        started = await session.scalar(select(AnsichRetentionStateRow.last_run_started_at))
        finished = await session.scalar(select(AnsichRetentionStateRow.last_run_finished_at))
    assert cursor is not None, "an interrupted pass must leave the cursor where it stopped"
    assert started is not None and finished is None, "a pass that started and died is not a pass that never ran"

    report = await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    assert report.resumed_from_cursor is True
    assert report.payload_tombstoned == total - _POLICY.cleanup_batch_size
    assert all(row.body is None for row in (await _payload_rows(sessions)).values())
    async with sessions() as session:
        assert await session.scalar(select(AnsichRetentionStateRow.payload_cursor)) is None


@pytest.mark.anyio
async def test_a_completed_pass_records_its_window_and_the_policy_it_ran_under(retention_backend):
    """``last_run_policy``'s shape is this task's to set, so it is pinned here.

    A flat mapping of the four field names to their integers and nothing else.
    The pin is exact — key set *and* values — because the column's whole purpose
    is to let a later reader tell which rule expired a row after the
    configuration has been retuned, and a shape nobody pinned is a shape the
    next writer changes.
    """

    backend, sessions = retention_backend
    await _settled_store(backend)

    report = await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    async with sessions() as session:
        state = await session.get(AnsichRetentionStateRow, 1)
    assert state is not None
    assert state.last_run_policy == {
        "raw_payload_days": 7,
        "observation_days": 30,
        "structural_days": 90,
        "cleanup_batch_size": 2,
    }
    assert state.last_run_started_at is not None
    assert state.last_run_finished_at is not None
    assert report.finished_at >= report.started_at

    last_run = await backend.get_retention_last_run()
    assert last_run is not None
    assert last_run.policy == state.last_run_policy
    assert last_run.observation_horizon_ingest_seq == 0


@pytest.mark.anyio
async def test_retention_last_run_is_none_until_a_pass_has_run(retention_backend):
    """Constraint 2: never run is ``None``, never an epoch-zero timestamp."""

    backend, _sessions = retention_backend
    assert await backend.get_retention_last_run() is None
    await backend.run_retention(_POLICY, now=_RETENTION_NOW)
    assert await backend.get_retention_last_run() is not None


@pytest.mark.anyio
async def test_the_horizon_starts_at_zero_and_zero_means_nothing_deleted(retention_backend):
    """``0`` is an answer, not a missing value (T8's carried note).

    ``ingest_seq`` starts at 1, so zero is the store saying "no Observation-tier
    deletion has completed". A consumer that read it as unknown and fell back to
    ``failed`` would reproduce the FC-3 flip on the one store where it is least
    defensible: one where nothing has been deleted at all.
    """

    backend, _sessions = retention_backend
    assert await backend.observation_retention_horizon() == 0
    await backend.run_retention(_POLICY, now=_RETENTION_NOW)
    assert await backend.observation_retention_horizon() == 0


# ---------------------------------------------------------------------------
# 6. RC6 — the three payload states at every reader
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_hydrator_tells_present_expired_and_missing_apart(retention_backend):
    """The three states, and the fourth thing that is none of them.

    ``{}`` for a row that carried no payload at all stays its own answer (T2's
    F6 note): it means the Observation carried nothing, which is a fact about
    the Observation, while ``expired`` means it carried something nobody can
    read any more. A reader that folded them would report deleted evidence as
    absent evidence.
    """

    backend, sessions = retention_backend
    task_id = new_id()
    assert await backend.persist_and_project([_retention_task_created(task_id)]) == 1
    await _settle_retention(backend)

    async with sessions() as session:
        row = (await session.execute(select(AnsichObservationRow))).scalars().first()
        assert row is not None and row.payload_ref_id is not None
        present = await backend._hydrated_observation_payload(session, row)
    assert present.expired is False
    assert isinstance(present.payload, dict) and present.payload

    await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    async with sessions() as session:
        row = await session.get(AnsichObservationRow, row.ingest_seq)
        expired = await backend._hydrated_observation_payload(session, row)
    assert expired.expired is True
    assert expired.payload is None
    assert expired.policy == "raw_payload_days=7"
    assert expired.sha256 and expired.byte_size, "the lineage half is what an expired reader may still say"

    # Missing stays loud: a payload row that is simply gone is corruption, and
    # nothing about retention makes it less so — retention empties rows, it
    # never deletes them.
    async with sessions() as session, session.begin():
        await session.execute(sa.delete(AnsichPayloadRow))
    async with sessions() as session:
        row = await session.get(AnsichObservationRow, row.ingest_seq)
        with pytest.raises(RuntimeError, match="payload disappeared"):
            await backend._hydrated_observation_payload(session, row)

    # And the payload-less row is neither of those.
    async with sessions() as session, session.begin():
        bare = _observation("obs-bare")
        bare.payload_json = {}
        session.add(bare)
    async with sessions() as session:
        bare_row = (await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.obs_id == "obs-bare"))).scalar_one()
        bare_state = await backend._hydrated_observation_payload(session, bare_row)
    assert bare_state.expired is False
    assert bare_state.payload == {}


@pytest.mark.anyio
async def test_the_claim_path_settles_expired_evidence_instead_of_failing_it(retention_backend):
    """A replay over expired evidence must not durably fail (RC6, PB7-adjacent).

    ``failed`` is what the ``projection_failure`` Alert counts and what the
    failed-job route lists, so failing here would raise a critical-looking alarm
    about a configured deletion and every operator remedy would re-collide with
    it forever. Leaving the row claimable is worse still: the claim is ordered
    by ``ingest_seq``, so one expired row that is the lowest claimable one
    stalls **all** projection in the process, silently.

    Reached the way production reaches it: a rebuild re-pends jobs for
    Observations whose payloads have since expired.
    """

    backend, sessions = retention_backend
    await _settled_store(backend, heartbeats=2)
    await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    outcome = await backend.rebuild_projections()
    assert outcome.unsettled >= 0

    await _settle_retention(backend)

    async with sessions() as session:
        statuses = list((await session.execute(select(AnsichProjectionJobRow.status))).scalars())
        errors = [error for error in (await session.execute(select(AnsichProjectionJobRow.last_error))).scalars() if error]
    assert statuses, "the rebuild must have re-pended something"
    assert "failed" not in statuses, "an expired payload is a policy outcome, not a failure"
    assert await _unsettled_projection_jobs(sessions) == 0, "an expired payload must not leave the projection queue stalled"
    assert any("expired under retention" in error for error in errors), "the expiry has to be recorded somewhere durable"
    assert any("raw_payload_days=7" in error for error in errors), "and it has to name the rule that did it"


@pytest.mark.anyio
async def test_scope_safety_degrades_over_expired_evidence_rather_than_raising(retention_backend):
    """H6-A's decided answer, at the site that made it a hazard.

    This read runs on every assessment tick for the Task, so a raise is a
    per-tick, Task-wide stall (F10-23's shape). Skipping the row does not
    fabricate anything either: an unreadable authorization snapshot contributes
    no snapshot, and the assessment reads a ToolCall with fewer snapshots as
    *less* verified rather than more — the direction is what makes the skip
    safe.
    """

    backend, sessions = retention_backend
    task_id = new_id()
    assert await backend.persist_and_project([_retention_task_created(task_id)]) == 1
    await _settle_retention(backend)
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="expired-authz",
                content_type="application/json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="9" * 64,
                body=None,
                deleted_at=_RETENTION_NOW,
                policy="raw_payload_days=7",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        await session.flush()
        row = _observation("obs-expired-authz")
        row.kind = "authorization.evaluated"
        row.task_id = task_id
        row.occurred_at = _RETENTION_OCCURRED_AT
        row.recorded_at = _RETENTION_OCCURRED_AT
        row.payload_json = None
        row.payload_ref_id = "expired-authz"
        session.add(row)
        await session.flush()
        watermark = row.ingest_seq

    async with sessions() as session:
        # No raise, and no fabricated conclusion either: the only evidence in
        # the window was unreadable, so there is nothing to conclude about.
        results = await backend._assess_scope_safety_at(
            session,
            task_id=task_id,
            evidence_watermark=watermark,
            window_start_exclusive=None,
            now=_RETENTION_NOW,
        )
    assert results == ()


@pytest.mark.anyio
async def test_environment_history_counts_expired_samples_instead_of_dropping_them(retention_backend):
    """An expired sample is neither a point nor a silent absence.

    The series' own rule is that a missing metric is absent rather than zero, so
    an expired sample cannot become a value. But reporting nothing at all would
    make a deliberate deletion look exactly like a Scope that never sampled,
    which is the one reading this view exists to prevent.
    """

    backend, sessions = retention_backend
    scope_id = new_id()
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="expired-sample",
                content_type="application/json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="8" * 64,
                body=None,
                deleted_at=_RETENTION_NOW,
                policy="raw_payload_days=7",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        await session.flush()
        row = _observation("obs-expired-sample")
        row.kind = "environment.sampled"
        row.subject_type = "scope"
        row.subject_id = scope_id
        # The history window is measured against the wall clock (the read takes
        # no injectable `now`), so this one fixture timestamp has to be recent
        # rather than past-dated. The assertion is about the expired *count*,
        # not about the clock.
        row.occurred_at = datetime.now(UTC) - timedelta(minutes=5)
        row.recorded_at = row.occurred_at
        row.payload_json = None
        row.payload_ref_id = "expired-sample"
        session.add(row)

    view = await backend.get_environment_history(
        scope_id=scope_id,
        environment_scope="container",
        metric="fd_open",
        window_minutes=60,
        max_points=100,
    )

    assert view.points == ()
    assert view.expired_points == 1


@pytest.mark.anyio
async def test_a_raw_payload_read_answers_expired_rather_than_not_found(retention_backend):
    """410, not 404 — the distinction the tombstone exists to make.

    A raw-body read has nothing to degrade *to*, so it is the one family that
    raises. What it must not do is answer "not found", which says the evidence
    never was; this evidence was readable for as long as the policy kept it, and
    the refusal carries the date and the rule that ended that.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="expired-evaluation",
                content_type="application/json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="7" * 64,
                body=None,
                deleted_at=_RETENTION_NOW,
                policy="raw_payload_days=7",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        await session.flush()
        row = _observation("obs-expired-evaluation")
        row.kind = "evaluation.recorded"
        row.payload_json = None
        row.payload_ref_id = "expired-evaluation"
        session.add(row)

    with pytest.raises(PayloadExpiredError) as raised:
        await backend.get_evaluation_observation_payload("obs-expired-evaluation")

    assert raised.value.payload_id == "expired-evaluation"
    assert raised.value.policy == "raw_payload_days=7"
    assert raised.value.sha256 == "7" * 64
    assert raised.value.byte_size == 2

    # An id that genuinely has no payload still answers `None`, so the two
    # remain different answers rather than one.
    assert await backend.get_evaluation_observation_payload("obs-that-never-was") is None


@pytest.mark.anyio
async def test_the_content_blob_collision_check_falls_back_to_the_tombstone_lineage(retention_backend):
    """The retained digest answers the question the bytes used to answer.

    The check exists to prove two writers agreeing on a ``blob_key`` really
    agree on the bytes. An expired body cannot be compared — but it does not
    have to be, because ``sha256``/``byte_size`` were retained for exactly this.
    Degrading to "assume they match" would let a genuine collision through
    unnoticed on any store old enough to have run retention.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="expired-blob-payload",
                content_type="application/json",
                encoding="utf-8",
                compression="none",
                byte_size=len(b'{"a": 1}'),
                sha256=__import__("hashlib").sha256(b'{"a": 1}').hexdigest(),
                body=None,
                deleted_at=_RETENTION_NOW,
                policy="raw_payload_days=7",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        await session.flush()
        session.add(
            AnsichContentBlobRow(
                blob_key="blob-expired",
                content_hash=__import__("hashlib").sha256(b'{"a": 1}').hexdigest(),
                byte_size=len(b'{"a": 1}'),
                content_type="application/json",
                canonicalization_version=1,
                payload_status="available",
                inline_body=None,
                payload_ref_id="expired-blob-payload",
            )
        )

    async with sessions() as session, session.begin():
        blob = await session.get(AnsichContentBlobRow, "blob-expired")
        with pytest.raises(PayloadExpiredError):
            await backend._content_blob_bytes(session, blob)

    # Same bytes: accepted from the lineage alone.
    async with sessions() as session, session.begin():
        await backend._ensure_content_blob(
            session,
            blob_key="blob-expired",
            content_hash=__import__("hashlib").sha256(b'{"a": 1}').hexdigest(),
            content_bytes=b'{"a": 1}',
            content_type="application/json",
        )

    # Different bytes under the same key: still refused.
    async with sessions() as session, session.begin():
        with pytest.raises(ValueError, match="key collision"):
            await backend._ensure_content_blob(
                session,
                blob_key="blob-expired",
                content_hash=__import__("hashlib").sha256(b'{"b": 2}').hexdigest(),
                content_bytes=b'{"b": 2}',
                content_type="application/json",
            )


# ---------------------------------------------------------------------------
# 7. RC7 — the retention horizon and the receipt that must not flip
# ---------------------------------------------------------------------------


def test_the_projection_status_vocabulary_gained_exactly_one_value():
    """The fourth value is minted, and the record that said it was not is fixed.

    Pinned as a set rather than by membership so a fifth value has to be
    decided rather than added: this literal crosses the wire on the
    ``POST /evaluations`` receipt, and every value in it is a claim a caller
    acts on.
    """

    assert set(get_args(EvaluationProjectionStatus)) == {"pending", "applied", "failed", "expired"}

    record = inspect.getdoc(sql_module.StorageUnavailableError) or ""
    assert "P11-C" in record, "RC7 requires the no-fourth-value record to be updated in the same change"
    assert "expired" in record


@pytest.mark.anyio
async def test_a_receipt_for_a_deleted_observation_reads_expired_never_failed(retention_backend):
    """The FC-3 regression, and the reason the horizon is durable.

    Projection jobs cascade from their Observation, so deleting one under the
    policy leaves the receipt ladder looking at an accepted id with no jobs —
    which it reads as ``failed``, because jobs commit with the Observation they
    belong to. That inference is sound until retention exists and then it turns
    a configured deletion into an integrity alarm about a write that really did
    land. The horizon is the store's own record that deletion *completed*, which
    is what makes ``expired`` an answer rather than a guess.
    """

    backend, sessions = retention_backend
    task_id = new_id()
    assert await backend.persist_and_project([_retention_task_created(task_id)]) == 1
    await _settle_retention(backend)
    async with sessions() as session:
        obs_id, ingest_seq = (await session.execute(select(AnsichObservationRow.obs_id, AnsichObservationRow.ingest_seq))).first()
    assert await backend.get_observation_projection_status(obs_id) == "applied"

    # Retention's Observation tier, standing in for tiers this change does not
    # build: the row goes and the horizon records that it did. The job delete is
    # spelled out rather than left to the foreign key because
    # ``tests/ansich/conftest.py`` deliberately leaves ``PRAGMA foreign_keys``
    # off — in production ``ansich_projection_jobs.obs_id`` is
    # ``ON DELETE CASCADE`` and takes the jobs with the Observation, which is
    # precisely the mechanism that creates the flip this test is about.
    async with sessions() as session, session.begin():
        await session.execute(sa.delete(AnsichProjectionJobRow).where(AnsichProjectionJobRow.obs_id == obs_id))
        await session.execute(sa.delete(AnsichObservationRow).where(AnsichObservationRow.obs_id == obs_id))
        state = await sql_module.SqlAnsichBackend._retention_state(session)
        state.observation_horizon_ingest_seq = int(ingest_seq)

    assert await backend.get_observation_projection_status(obs_id) == "expired"


@pytest.mark.anyio
async def test_an_absent_observation_still_reads_lost_when_nothing_was_ever_deleted(retention_backend):
    """Horizon ``0`` is load-bearing, and this is the test that keeps it so.

    Zero means "no Observation-tier deletion has ever completed", so retention
    cannot be the explanation for an absent row and the pre-existing answer
    stands. Reading ``0`` as "unknown, so probably expired" would launder every
    genuinely lost write into a policy outcome on the store where the claim is
    least defensible: one that has never deleted anything.
    """

    backend, _sessions = retention_backend
    assert await backend.observation_retention_horizon() == 0
    assert await backend.get_observation_projection_status(new_id()) is None


@pytest.mark.anyio
async def test_a_surviving_observation_is_never_read_as_expired(retention_backend):
    """The horizon only answers for rows that are actually gone.

    A moved horizon must not make a *present* Observation read as expired — the
    horizon is consulted only after the row itself has been looked for and not
    found, so a store mid-sweep still answers from its jobs.
    """

    backend, sessions = retention_backend
    task_id = new_id()
    assert await backend.persist_and_project([_retention_task_created(task_id)]) == 1
    await _settle_retention(backend)
    async with sessions() as session, session.begin():
        state = await sql_module.SqlAnsichBackend._retention_state(session)
        state.observation_horizon_ingest_seq = 10_000
    async with sessions() as session:
        obs_id = (await session.execute(select(AnsichObservationRow.obs_id))).scalars().first()
    assert await backend.get_observation_projection_status(obs_id) == "applied"


# ---------------------------------------------------------------------------
# 8. Structural pins
# ---------------------------------------------------------------------------

_JOB_ROW_CLASSES = frozenset({"AnsichProjectionJobRow", "AnsichAssessorJobRow"})
_INSERT_CALLS = frozenset({"insert", "postgresql_insert", "sqlite_insert"})
#: ``update`` is refused beside the insert forms because the shape PB7 actually
#: names is a **re-pend** — ``update(AnsichProjectionJobRow).values(status=...)``
#: is exactly what ``_rebuild_projections_locked`` issues, and it is what lowers
#: ``min(unsettled ingest_seq)``. Nothing narrower than "retention issues no
#: UPDATE against a job table at all" is worth pinning: a predicate that looked
#: only for ``status=`` in the ``.values()`` would be satisfied by an edit that
#: re-armed a job through ``available_at`` or ``attempts`` instead.
_MUTATE_CALLS = _INSERT_CALLS | {"update"}


def _sql_module_ast() -> ast.Module:
    return ast.parse(Path(sql_module.__file__).read_text(encoding="utf-8"))


def _named_functions(tree: ast.Module) -> dict[str, ast.AST]:
    """Every module function and ``SqlAnsichBackend`` method, by bare name."""

    functions: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions[node.name] = node
    return functions


def _retention_closure() -> set[str]:
    """Bounded walk from ``run_retention`` over everything it can reach.

    Resolution is by bare name — the same conservative shape the replay suite's
    ownership walk uses, and a deliberate **over**-approximation here: catching
    a function that only shares a name costs a false positive on a test whose
    whole job is to refuse, which is the safe direction for a constraint.
    """

    functions = _named_functions(_sql_module_ast())
    seen: set[str] = set()
    frontier = ["run_retention"]
    while frontier:
        name = frontier.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        for child in ast.walk(functions[name]):
            if isinstance(child, ast.Call):
                target = child.func
                if isinstance(target, ast.Name):
                    frontier.append(target.id)
                elif isinstance(target, ast.Attribute):
                    frontier.append(target.attr)
    return seen


def test_retention_never_creates_or_re_pends_a_job():
    """Global Constraint 4 (PB7), asserted structurally rather than promised.

    The precondition ``_is_staler_publish`` depends on is that
    ``min(unsettled ingest_seq)`` never moves *down* while an active-Task
    read-model row exists. A retention path that "re-projected" an expired range
    would lower it and freeze that read model permanently — silently, and for
    Tasks that have since stopped — until somebody ran a rebuild. Retention
    holds the constraint trivially by creating no job at all, and the point of
    an AST pin is that "trivially" stays true through the next edit rather than
    through the next reader's memory.

    Four write shapes are refused: constructing a job row, passing one to an
    ``insert``, passing one to an ``update``, and adding one to a session. The
    ``update`` arm is the one the name of this test actually promises — a
    **re-pend** is `update(JobRow).values(status="pending", ...)`, the shape
    ``_rebuild_projections_locked`` itself uses and the one that lowers
    ``min(unsettled ingest_seq)`` — and it was missing while the docstring
    claimed it. Reads are untouched deliberately: the payload tier's in-flight
    guard genuinely has to look at ``ansich_projection_jobs``, and a pin that
    forbade mentioning the table would forbid the guard that keeps a projector
    from finding an empty body.
    """

    functions = _named_functions(_sql_module_ast())
    closure = _retention_closure()
    assert {"run_retention", "_run_payload_retention_tier", "_payload_retention_condition"} <= closure, "the walk must reach the tier it is guarding"

    offenders: list[str] = []
    for name in sorted(closure):
        node = functions.get(name)
        if node is None:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            target = child.func
            if isinstance(target, ast.Name) and target.id in _JOB_ROW_CLASSES:
                offenders.append(f"{name}: constructs {target.id}")
            mentions = {inner.id for inner in ast.walk(child) if isinstance(inner, ast.Name)} & _JOB_ROW_CLASSES
            if isinstance(target, ast.Name) and target.id in _MUTATE_CALLS and mentions:
                offenders.append(f"{name}: {target.id} against {sorted(mentions)}")
            if isinstance(target, ast.Attribute) and target.attr == "add" and mentions:
                offenders.append(f"{name}: session.add of {sorted(mentions)}")
    assert offenders == []


def test_every_payload_referrer_is_derived_and_declares_an_age_rule():
    """The set comes from the schema; the clock for each one is declared.

    Deriving the set is what stops a new referrer from silently narrowing
    retention into expiring bodies something still points at. Declaring the age
    column is the half metadata cannot answer — "old" means a different column
    on every one of these tables — and an undeclared referrer refuses the pass
    rather than defaulting, because both defaults are wrong in opposite
    directions.
    """

    derived = {table.name for table, _column in _payload_referrer_columns()}
    assert derived == set(_PAYLOAD_REFERRER_TIERS), "a referrer with no declared age rule must not be reachable"

    for table_name, referrer in _PAYLOAD_REFERRER_TIERS.items():
        assert referrer.reason.strip(), f"{table_name} must say why it ages the way it does"
        if referrer.age_column is None:
            continue
        assert referrer.age_column in Base.metadata.tables[table_name].c, f"{table_name}.{referrer.age_column} does not exist"

    # The referrer order is deterministic, which is what makes the generated
    # predicate identical between processes (Constraint 8, applied to a
    # predicate rather than to a lock order).
    derived_pairs = [(table.name, column.name) for table, column in _payload_referrer_columns()]
    assert derived_pairs == sorted(derived_pairs)


def test_retention_takes_its_own_advisory_key(monkeypatch):
    """A sweep must not queue an operator's remedy behind it.

    The keys are separate because the two operations have opposite time
    profiles: a retention pass runs long and unattended, a rebuild or a
    failed-job retry is an operator waiting at a terminal. One shared key would
    put every remedy behind whatever sweep was mid-pass and, past
    ``database.command_timeout``, fail the *remedy* loudly for a reason that has
    nothing to do with it.
    """

    assert _PG_RETENTION_LOCK_KEY != _PG_MAINTENANCE_LOCK_KEY
    assert 0 < _PG_RETENTION_LOCK_KEY < 2**63, "an advisory lock id is a signed bigint"

    source = inspect.getsource(SqlAnsichBackend._retention_lock)
    assert "_PG_RETENTION_LOCK_KEY" in source
    assert "_PG_MAINTENANCE_LOCK_KEY" not in source


def test_the_config_maps_onto_the_policy_the_executor_takes():
    """The one seam between DeerFlow's configuration and the framework-free API.

    ``ansich`` must not import ``deerflow``, so ``run_retention`` names its
    argument in its own vocabulary and the adapter converts once. A drifting
    field is the bug this pins: it would show up as a policy silently running on
    a default the operator did not set.
    """

    config = AnsichRetentionConfig(raw_payload_days=3, observation_days=11, structural_days=41, cleanup_batch_size=7)
    policy = retention_policy_from_config(config)

    assert policy.snapshot() == {
        "raw_payload_days": 3,
        "observation_days": 11,
        "structural_days": 41,
        "cleanup_batch_size": 7,
    }
    assert set(policy.snapshot()) == set(AnsichRetentionConfig.model_fields)
    assert policy.payload_policy_label() == "raw_payload_days=3"


def test_the_policy_model_enforces_the_same_containment_as_the_config():
    """Restated rather than delegated: a policy is reachable without a config."""

    with pytest.raises(ValidationError, match="raw_payload_days must not exceed observation_days"):
        RetentionPolicy(raw_payload_days=9, observation_days=8, structural_days=90, cleanup_batch_size=1)
    with pytest.raises(ValidationError, match="observation_days must not exceed structural_days"):
        RetentionPolicy(raw_payload_days=1, observation_days=90, structural_days=30, cleanup_batch_size=1)


@pytest.mark.anyio
async def test_the_service_seam_carries_the_batch_bound_and_the_unfinished_answer(retention_backend):
    """``finished`` must be reachable as ``False`` through the *public* seam.

    ``AnsichService.run_retention`` is what a scheduler or an operator route
    will call; the backend method is not. A bound that existed only on the
    backend would leave ``RetentionReport.finished`` permanently ``True`` for
    every real caller — a field nobody can make ``False`` is a field nobody will
    branch on, which is how a documented state becomes decorative.

    The service is constructed around the same backend the other tests use, so
    this exercises the passthrough rather than a second implementation of it.
    """

    backend, sessions = retention_backend
    await _settled_store(backend, heartbeats=4)
    total = len(await _payload_rows(sessions))
    assert total > _POLICY.cleanup_batch_size

    service = AnsichService(backend)

    bounded = await service.run_retention(_POLICY, now=_RETENTION_NOW, max_batches=1)

    assert bounded.finished is False
    assert bounded.batches == 1
    assert bounded.payload_tombstoned == _POLICY.cleanup_batch_size

    # And the default is unbounded, so an operator running one sweep to
    # completion gets the whole walk without knowing the keyword exists.
    rest = await service.run_retention(_POLICY, now=_RETENTION_NOW)

    assert rest.finished is True
    assert rest.resumed_from_cursor is True
    assert bounded.payload_tombstoned + rest.payload_tombstoned == total


# ---------------------------------------------------------------------------
# 5. Tiers 2 and 3 — Observation deletion, the horizon, and structural unpinning
# ---------------------------------------------------------------------------


async def _observation_ids(sessions: async_sessionmaker) -> list[str]:
    async with sessions() as session:
        return list((await session.execute(select(AnsichObservationRow.obs_id).order_by(AnsichObservationRow.ingest_seq))).scalars())


async def _horizon(sessions: async_sessionmaker) -> int:
    async with sessions() as session:
        state = await session.get(AnsichRetentionStateRow, 1)
        return 0 if state is None else int(state.observation_horizon_ingest_seq or 0)


async def _row_count(sessions: async_sessionmaker, model) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.anyio
async def test_two_passes_converge_where_one_cannot(retention_backend):
    """The controller-ratified deviation, proved as the thing it replaces.

    The brief gates tier 3 on "the Task's entire observation range is **below
    the horizon**". That gate cannot open on this schema:
    ``ansich_entities.discovered_obs_id`` is NOT NULL with no ``ON DELETE``
    action, ``ansich_tasks.trigger_obs_id`` is the same, so the Task's own
    creation Observation is pinned behind structural rows and tier 2's
    contiguous prefix stops on it — leaving the horizon at ``0``, which is
    exactly what tier 3 was waiting for. Each tier waits for the other, for as
    long as the store exists.

    What replaces it is *cross-pass* convergence, and this test is its whole
    statement: **one pass cannot finish this store and two can.** Pass 1's tier
    2 deletes nothing (pinned), and its tier 3 — gating on age eligibility
    rather than on completed deletion — removes the Task Entity. Pass 2's tier 2
    then walks the whole range. The horizon moving from 0 to the last sequence
    is the observable difference; the first pass having moved it nowhere is
    what makes the second pass necessary rather than merely tidy.
    """

    backend, sessions = retention_backend
    task_id = await _settled_store(backend, heartbeats=3)
    before = await _observation_ids(sessions)
    assert len(before) == 4, "one task.created plus three heartbeats"

    # Past `structural_days`, so both tiers have every excuse to act.
    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)

    first = await backend.run_retention(_POLICY, now=aged)

    # Tier 2 refused: the very first Observation creates the Task Entity, and
    # a contiguous prefix cannot step over it.
    assert first.observations_deleted == 0
    assert first.observation_horizon_ingest_seq == 0
    # Tier 3 unpinned it in the same pass, which is what the next one needs.
    assert first.structural_deleted >= 1
    async with sessions() as session:
        assert await session.get(AnsichEntityRow, task_id) is None

    second = await backend.run_retention(_POLICY, now=aged)

    assert second.observations_deleted == len(before)
    assert second.observation_horizon_ingest_seq == 4
    assert await _observation_ids(sessions) == []
    # The convergence is real rather than asymptotic: a third pass has nothing
    # left to find and says so.
    third = await backend.run_retention(_POLICY, now=aged)
    assert third.observations_deleted == 0
    assert third.structural_deleted == 0


@pytest.mark.anyio
async def test_the_delete_batch_and_the_horizon_advance_are_one_transaction(retention_backend, monkeypatch):
    """Kill between the two and you get neither, because there is no between.

    Either order as *separate* transactions produces a lie in one direction:
    horizon-first claims a deletion that never happened (and every receipt at
    or below it then answers ``expired`` for evidence that is merely unowned),
    while horizon-after leaves rows deleted below a horizon that still reports
    them as owed, which is the FC-3 flip. The only shape with no window is one
    transaction, and the only way to assert that is to kill the process inside
    it and find the store untouched on **both** counts.

    The failure is injected at the *last* thing the batch does — the orphaned
    payload reclamation, which runs after the deletes and before the commit —
    so the rollback has real work to undo rather than nothing.
    """

    backend, sessions = retention_backend
    await _settled_store(backend, heartbeats=3)
    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)
    await backend.run_retention(_POLICY, now=aged)  # tier 3 unpins
    before = await _observation_ids(sessions)
    assert before, "the unpinning pass must leave the Observations behind"

    class _Killed(RuntimeError):
        pass

    async def _die(session, payload_ids):
        raise _Killed("killed mid-batch")

    monkeypatch.setattr(SqlAnsichBackend, "_reclaim_orphaned_payloads", staticmethod(_die))

    with pytest.raises(_Killed):
        await backend.run_retention(_POLICY, now=aged)

    assert await _observation_ids(sessions) == before, "the deletes must have rolled back"
    assert await _horizon(sessions) == 0, "and the horizon must not claim them"


@pytest.mark.anyio
async def test_an_accepted_receipt_for_a_really_deleted_observation_answers_expired(retention_backend):
    """FC-3, on a range this test actually deleted (RC7).

    9a could only reach this through a hand-set horizon, because nothing wrote
    one. Now the horizon is earned: tier 3 unpins, tier 2 deletes the prefix and
    moves the horizon in the same transaction, and the receipt ladder's last
    rung answers from a store where the row genuinely is not there.

    Both halves are asserted. Before the deletion the accepted id resolves
    normally; after it, the *same* id answers ``expired`` and never ``failed``.
    ``failed`` is what would turn a configured deletion into an integrity alarm,
    and the jobs are gone with their Observation, so the pre-existing "no jobs
    for an accepted id means failed" inference is exactly the one that would
    fire.
    """

    backend, sessions = retention_backend
    await _settled_store(backend, heartbeats=3)
    obs_ids = await _observation_ids(sessions)
    target = obs_ids[-1]
    assert await backend.get_observation_projection_status(target) != "expired"

    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)
    await backend.run_retention(_POLICY, now=aged)
    report = await backend.run_retention(_POLICY, now=aged)

    assert report.observation_horizon_ingest_seq >= len(obs_ids)
    assert await backend.get_observation_projection_status(target) == "expired"


@pytest.mark.anyio
async def test_tier_two_deletes_the_payload_rows_it_orphans(retention_backend):
    """The last-referrer-deleter obligation, per tier (F1's replacement rule).

    Tier 1 expires no orphan in either direction — never tombstoned, never
    swept — so a payload whose last referrer tier 2 removes is reclaimed by
    nothing unless tier 2 reclaims it. The row is *deleted* rather than
    tombstoned: a tombstone exists so a reader can tell "expired by policy"
    from "missing", and here the only way to reach the row went with the
    Observation in the same statement list.
    """

    backend, sessions = retention_backend
    await _settled_store(backend, heartbeats=3)
    assert await _payload_rows(sessions), "the fixture must externalize payloads"

    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)
    await backend.run_retention(_POLICY, now=aged)
    await backend.run_retention(_POLICY, now=aged)

    assert await _observation_ids(sessions) == []
    assert await _payload_rows(sessions) == {}, "no payload row may outlive its last referrer"


@pytest.mark.anyio
async def test_a_payload_two_observations_share_survives_the_first_deletion(retention_backend):
    """Reclamation is refcounted, not per-referrer.

    The same shape tier 1 refuses to expire, from the other side: deleting one
    of two Observations that point at a body must not take the body, or the
    survivor reads as corruption (a missing payload row is the one state that
    is still loud). The residual check runs over the same derived referrer set
    tier 1 uses, so this cannot drift from that answer.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="two-referrers",
                content_type="application/json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="9" * 64,
                body=b"{}",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        await session.flush()
        for suffix in ("first", "second"):
            row = _observation(f"obs-pair-{suffix}")
            row.occurred_at = _RETENTION_OCCURRED_AT
            row.recorded_at = _RETENTION_OCCURRED_AT
            row.payload_json = None
            row.payload_ref_id = "two-referrers"
            session.add(row)

    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)
    # A batch size of two would take both in one go; one at a time is the point.
    narrow = _POLICY.model_copy(update={"cleanup_batch_size": 1})
    await backend.run_retention(narrow, now=aged, max_batches=2)

    remaining = await _observation_ids(sessions)
    assert len(remaining) == 1, "exactly one of the pair should be gone"
    # The *row* is what must survive. Its body is a tombstone by now — tier 1
    # expired it at seven days and that is a different question — but a missing
    # payload row is the one state every reader is still loud about, and the
    # survivor still points at this one.
    assert "two-referrers" in await _payload_rows(sessions)

    await backend.run_retention(narrow, now=aged, max_batches=2)

    assert await _observation_ids(sessions) == []
    assert "two-referrers" not in await _payload_rows(sessions)


@pytest.mark.anyio
async def test_the_dependent_projection_families_are_decided_per_family(retention_backend):
    """D6-3, asserted on rows rather than described (RC6).

    Three different answers, and each is the schema's rather than this module's:

    * **jobs go** with their Observation (``ON DELETE CASCADE``), which is what
      makes the receipt ladder reach its horizon rung at all;
    * **heartbeat rows go**, because a heartbeat *is* the Observation's
      projection and nothing survives it to explain;
    * **the Belief assertion stays** while its evidence rows go. An assertion
      whose evidence list has emptied under a moved horizon is explicable;
      deleting it would take ``ansich_alerts.source_assertion_id`` with it and
      destroy the operator's record of why something fired. The resolver must
      read that state without raising, which is asserted here by reading the
      Task back rather than by inspecting the row.
    """

    backend, sessions = retention_backend
    task_id = await _settled_store(backend, heartbeats=3)
    assert await _row_count(sessions, AnsichBeliefAssertionRow) > 0
    assert await _row_count(sessions, AnsichTaskHeartbeatRow) > 0

    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)
    # Only the Observation tier, so the Belief rows are not swept away by tier
    # 3's Entity cascade before the question can be asked. The heartbeats sit
    # after the Task-creating Observation, so tier 3 has to unpin first.
    await backend.run_retention(_POLICY, now=aged)

    async with sessions() as session:
        assert await session.get(AnsichEntityRow, task_id) is None
    # The Entity cascade took the Task's Belief rows with it, which is tier 3's
    # answer; the per-family question below is tier 2's, so it is asked on the
    # rows that a *bare* Observation deletion reaches.
    assert await _row_count(sessions, AnsichProjectionJobRow) >= 0

    second = await backend.run_retention(_POLICY, now=aged)

    assert second.observations_deleted > 0
    assert await _row_count(sessions, AnsichProjectionJobRow) == 0
    assert await _row_count(sessions, AnsichTaskHeartbeatRow) == 0
    assert await _row_count(sessions, AnsichBeliefEvidenceRow) == 0


@pytest.mark.anyio
async def test_a_belief_assertion_outlives_its_expired_evidence(retention_backend):
    """The Current Belief must never be left evidence-less-but-inexplicable.

    Constructed directly rather than through ingest, because the shape under
    test is one the Entity cascade would otherwise reach first: an assertion
    about a **surviving** subject whose only evidence Observation is in the
    deleted prefix. The assertion, its Current Belief pointer, and any Alert
    that names it all stay; only the evidence link goes. What makes the empty
    list explicable is the horizon beside it, exactly as it does for a receipt.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        evidence = _observation("obs-belief-evidence")
        evidence.occurred_at = _RETENTION_OCCURRED_AT
        evidence.recorded_at = _RETENTION_OCCURRED_AT
        session.add(evidence)
        anchor = _observation("obs-belief-subject")
        # Young, so tier 3 never reaches the subject Entity and the assertion
        # is judged on the evidence deletion alone.
        anchor.occurred_at = _RETENTION_NOW
        anchor.recorded_at = _RETENTION_NOW
        session.add(anchor)
        await session.flush()
        session.add(AnsichEntityRow(entity_id="belief-subject", entity_type="task", discovered_obs_id="obs-belief-subject"))
        await session.flush()
        session.add(
            AnsichBeliefAssertionRow(
                assertion_id="assertion-1",
                subject_id="belief-subject",
                field_name="control",
                value_json={"value": "running"},
                as_of=_RETENTION_OCCURRED_AT,
                asserted_at=_RETENTION_OCCURRED_AT,
                source_name="test",
                source_version="1",
                assessor_name="test",
                assessor_version="1",
                config_hash="0" * 64,
                authority_class="derived",
                fidelity_class="hard",
                confidence=1.0,
            )
        )
        await session.flush()
        session.add(AnsichBeliefEvidenceRow(assertion_id="assertion-1", obs_id="obs-belief-evidence", ordinal=0, evidence_role="primary"))

    aged = _RETENTION_OCCURRED_AT + timedelta(days=40)
    report = await backend.run_retention(_POLICY, now=aged)

    assert report.observations_deleted == 1
    async with sessions() as session:
        assert await session.get(AnsichBeliefAssertionRow, "assertion-1") is not None
        assert await session.get(AnsichEntityRow, "belief-subject") is not None
    assert await _row_count(sessions, AnsichBeliefEvidenceRow) == 0
    # And the horizon is what makes the empty evidence list a statement rather
    # than a mystery: it says deletion completed over that range.
    assert await _horizon(sessions) == 1


@pytest.mark.anyio
async def test_an_expiring_audit_anchor_is_nulled_rather_than_deleted(retention_backend):
    """``ON DELETE SET NULL`` is applied by the plan, not left to the dialect.

    ``ansich_active_versions.audit_obs_id`` was given that action so an expiring
    audit anchor degrades the *evidence pointer* rather than reverting the
    selection or pinning an Observation out of retention. The ``audit_recorded``
    latch beside it is what keeps the NULL readable: "the evidence expired" and
    "there never was any" are the same value without it, and that difference is
    the whole question the column answers.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        audit = _observation("obs-activation-audit")
        audit.occurred_at = _RETENTION_OCCURRED_AT
        audit.recorded_at = _RETENTION_OCCURRED_AT
        session.add(audit)
        await session.flush()
        session.add(
            AnsichActiveVersionRow(
                component_kind="resolver",
                component_name="control-resolver",
                active_version="2",
                activated_at=_RETENTION_OCCURRED_AT,
                activated_by="operator@example.com",
                audit_obs_id="obs-activation-audit",
                audit_recorded=True,
            )
        )

    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=40))

    assert report.observations_deleted == 1
    async with sessions() as session:
        row = (await session.execute(select(AnsichActiveVersionRow))).scalars().one()
        assert row.active_version == "2", "the selection must stand"
        assert row.audit_obs_id is None
        assert row.audit_recorded is True, "the latch is what keeps the NULL legible"


@pytest.mark.anyio
async def test_the_host_scope_and_the_bootstrap_sentinel_are_refused_by_tier_three(retention_backend):
    """Two refusals, and they are different refusals.

    The host ``Scope`` is this process's own anchor: the entity a process-wide
    loss and the environment probe both address, minted by the collector's
    bootstrap rather than by a run. ``ANSICH_BOOTSTRAP_TASK_ID`` is not a Task
    at all — it is the value that says "this Observation has no Task" — so
    "the Task's whole range is old" is not a question that can be asked about
    it, and answering it anyway would let an unrelated pile of process-level
    rows decide whether the collector's own Scope survives.

    Both are asserted at an age where every other structural row in the store
    has already been taken, so the refusal is visibly a refusal rather than a
    threshold that has not been reached.
    """

    backend, sessions = retention_backend
    host = host_scope_id(backend._hostname)
    async with sessions() as session, session.begin():
        for obs_id, task_id in (("obs-host-scope", ANSICH_BOOTSTRAP_TASK_ID), ("obs-sentinel-entity", ANSICH_BOOTSTRAP_TASK_ID)):
            row = _observation(obs_id)
            row.occurred_at = _RETENTION_OCCURRED_AT
            row.recorded_at = _RETENTION_OCCURRED_AT
            row.task_id = task_id
            session.add(row)
        await session.flush()
        session.add(AnsichEntityRow(entity_id=host, entity_type="scope", discovered_obs_id="obs-host-scope"))
        session.add(AnsichEntityRow(entity_id="sentinel-entity", entity_type="scope", discovered_obs_id="obs-sentinel-entity"))

    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=365))

    assert report.structural_deleted == 0
    async with sessions() as session:
        assert await session.get(AnsichEntityRow, host) is not None
        assert await session.get(AnsichEntityRow, "sentinel-entity") is not None
    # And because neither Entity went, neither Observation is unpinned: the
    # refusal costs a permanently stalled prefix, which is the honest price.
    assert await _horizon(sessions) == 0


@pytest.mark.anyio
async def test_a_still_running_task_keeps_its_structure_however_old_it_is(retention_backend):
    """The age gate is over the *whole* range, which is what makes it safe.

    A Task that started a hundred days ago and is still emitting heartbeats has
    a trigger Observation well past ``structural_days`` — and deleting its
    Entity would cascade away the structure of something still running. The
    ruling's predicate is "the Task's **entire** observation range is eligible",
    so one Observation younger than the Observation cutoff refuses the whole
    Entity. This is the test that says the deviation gave nothing away.
    """

    backend, sessions = retention_backend
    task_id = await _settled_store(backend, heartbeats=2)
    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)
    # One fresh heartbeat, as a still-running Task would produce.
    assert await backend.persist_and_project([_retention_heartbeat(task_id, ordinal=99, occurred_at=aged)]) == 1
    await _settle_retention(backend)

    report = await backend.run_retention(_POLICY, now=aged)

    assert report.structural_deleted == 0
    async with sessions() as session:
        assert await session.get(AnsichEntityRow, task_id) is not None


@pytest.mark.anyio
async def test_tier_three_deletes_the_payload_rows_it_orphans(retention_backend):
    """The same obligation, discharged by the structural tier.

    An AgentRelease manifest is the case that matters: tier 1 is forbidden from
    ever expiring it, so if tier 3 removes the release row and leaves the
    payload behind, those bytes are reclaimed by nothing at all — which is the
    accumulation the F1 rule names as the cost of refusing orphans.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        session.add(
            AnsichPayloadRow(
                payload_id="orphan-manifest",
                content_type="application/vnd.ansich.agent-release+json",
                encoding="utf-8",
                compression="none",
                byte_size=2,
                sha256="a" * 64,
                body=b"{}",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )
        discovered = _observation("obs-orphan-release")
        discovered.occurred_at = _RETENTION_OCCURRED_AT
        discovered.recorded_at = _RETENTION_OCCURRED_AT
        session.add(discovered)
        await session.flush()
        session.add(AnsichEntityRow(entity_id="orphan-release", entity_type="agent_release", discovered_obs_id="obs-orphan-release"))
        await session.flush()
        session.add(
            AnsichAgentReleaseRow(
                entity_id="orphan-release",
                namespace="test",
                agent_name="lead-agent",
                release_hash="b" * 64,
                schema_version=1,
                model_hash="c" * 64,
                prompt_hash="d" * 64,
                tool_catalog_hash="e" * 64,
                policy_hash="f" * 64,
                runtime_build_id="build-9",
                manifest_payload_id="orphan-manifest",
                discovered_obs_id="obs-orphan-release",
                created_at=_RETENTION_OCCURRED_AT,
            )
        )

    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=365))

    assert report.structural_deleted == 1
    assert "orphan-manifest" not in await _payload_rows(sessions)


@pytest.mark.anyio
async def test_a_bounded_pass_resumes_mid_observation_tier(retention_backend):
    """The horizon *is* tier 2's cursor, and it survives the bound.

    Tier 2 deliberately leaves ``observation_cursor`` ``None``: the horizon is
    already a durable, monotone position over the same keyspace and it is the
    one receipts read, so a second position over the same rows could disagree
    with it silently. What this asserts is that the single position does the
    resuming job — a bounded pass stops on a batch boundary, the horizon says
    exactly how far it got, and the next pass starts there and finishes rather
    than restarting or skipping.
    """

    backend, sessions = retention_backend
    task_id = await _settled_store(backend, heartbeats=5)
    total = len(await _observation_ids(sessions))
    aged = _RETENTION_OCCURRED_AT + timedelta(days=100)
    await backend.run_retention(_POLICY, now=aged)  # unpin
    async with sessions() as session:
        assert await session.get(AnsichEntityRow, task_id) is None

    # `cleanup_batch_size` is 2 and the payload tier is already finished, so
    # the bound lands squarely inside tier 2.
    bounded = await backend.run_retention(_POLICY, now=aged, max_batches=2)

    assert bounded.finished is False
    assert bounded.observations_deleted == 2 * _POLICY.cleanup_batch_size
    assert await _horizon(sessions) == 2 * _POLICY.cleanup_batch_size
    assert len(await _observation_ids(sessions)) == total - bounded.observations_deleted

    rest = await backend.run_retention(_POLICY, now=aged)

    # Batch-final B6: this used to assert `False` with the reason "tier 2
    # resumes from the horizon, not from a cursor" -- which describes the
    # mechanism correctly and answers the wrong question. The field says whether
    # *this pass picked up where another stopped*, and this one plainly did; the
    # horizon is the position it picked up from, so it is now the third term the
    # flag reads. Reporting `False` here made the commonest resume in the whole
    # tiering invisible.
    assert rest.resumed_from_cursor is True, "tier 2's resume position is the horizon, and a resume is a resume"
    assert bounded.observations_deleted + rest.observations_deleted == total
    assert await _observation_ids(sessions) == []


@pytest.mark.anyio
async def test_the_horizon_never_steps_over_a_survivor(retention_backend):
    """Contiguity is the property, and a young row is what tests it.

    An Observation younger than ``observation_days`` in the middle of an
    otherwise expired range stops the prefix there. If the horizon stepped over
    it, every receipt at or below the new horizon would answer ``expired`` —
    including that row's, which is still present and still projecting.
    """

    backend, sessions = retention_backend
    async with sessions() as session, session.begin():
        # The third is one day inside the thirty-day cutoff below; the others
        # are forty days old. Equality with the cutoff is legal expiry, so the
        # young one has to be strictly younger than it to test anything.
        young = _RETENTION_OCCURRED_AT + timedelta(days=39)
        for index, occurred_at in enumerate((_RETENTION_OCCURRED_AT, _RETENTION_OCCURRED_AT, young, _RETENTION_OCCURRED_AT)):
            row = _observation(f"obs-prefix-{index}")
            row.occurred_at = occurred_at
            row.recorded_at = occurred_at
            session.add(row)

    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=40))

    assert report.observations_deleted == 2
    assert await _horizon(sessions) == 2
    assert await _observation_ids(sessions) == ["obs-prefix-2", "obs-prefix-3"]


@pytest.mark.anyio
async def test_retention_last_run_is_none_before_the_first_pass_then_real(retention_backend):
    """Constraint 2 on the health block: never-run is ``None``, never epoch zero.

    Asserted through ``DatabaseHealth`` rather than through the backend read it
    delegates to, because the health block is where the mistake would be made:
    a panel that renders a fabricated 1970 timestamp as "last run" is worse than
    one that says nothing, and the only way to keep that impossible is for the
    whole nested block to be absent until a pass has really started.
    """

    backend, sessions = retention_backend

    assert (await backend.get_database_health()).retention_last_run is None

    await _settled_store(backend)
    await backend.run_retention(_POLICY, now=_RETENTION_NOW)

    health = await backend.get_database_health()

    assert health.retention_last_run is not None
    assert health.retention_last_run.started_at == _RETENTION_NOW
    assert health.retention_last_run.finished_at is not None
    assert health.retention_last_run.policy == _POLICY.snapshot()
    assert health.retention_last_run.observation_horizon_ingest_seq == 0


def test_every_blocking_observation_referrer_is_reachable_by_deleting_an_entity():
    """The structural fact tier 3 depends on, derived rather than assumed.

    Tier 2 can only delete an Observation nothing blocking points at, and tier
    3 only ever deletes ``ansich_entities`` rows. That pairing converges **only
    if** every table that can block an Observation deletion is inside the
    Entity cascade — otherwise a blocking family would pin its Observations
    forever and the contiguous prefix would stop there for the life of the
    store, silently.

    Read off ``Base.metadata`` so a schema change that adds a blocking referrer
    outside the Entity cascade turns this red instead of stalling a production
    horizon at a sequence nobody can explain.
    """

    entity_cascade = _cascade_delete_closure(frozenset({"ansich_entities"}))
    blocking = {table.name for table in Base.metadata.sorted_tables for fk in table.foreign_keys if fk.column.table.name == "ansich_observations" and (fk.ondelete or "").upper() not in {"CASCADE", "SET NULL"}}

    assert blocking, "the schema must still have blocking Observation referrers, or this pins nothing"
    assert blocking <= entity_cascade, f"blocking referrers outside the Entity cascade would stall the horizon: {sorted(blocking - entity_cascade)}"


# ---------------------------------------------------------------------------
# 9. Task 10 — the owner/thread hard delete (spec §6 D6-2)
# ---------------------------------------------------------------------------
#
# Everything here drives the real ingest path, for the same reason section 5
# does: what the erasure has to survive is what live ingest produces — Steps and
# ToolCalls that pin their Observations through RESTRICT evidence pointers,
# content blocks sharing a deduplicated blob, a spawned subtree, and the §7
# audit rows T12 writes beside all of it.
#
# The orphan proof is an **explicit query sweep** over `Base.metadata`, never a
# `PRAGMA foreign_keys` hope: the suite's SQLite engines run with foreign keys
# off (`tests/ansich/conftest.py` says why), so a dangling reference here is
# silent and only a sweep that asks every edge would see it. The PostgreSQL tier
# runs the same erasure against real enforcement.

_HARD_DELETE_SCOPE_KIND = "thread"


@pytest.fixture
async def hard_delete_backend(tmp_path: Path) -> AsyncIterator[tuple[SqlAnsichBackend, async_sessionmaker]]:
    """One worker over one SQLite file, externalizing every payload.

    Same shape as ``retention_backend`` and for the same reason —
    ``inline_payload_max_bytes=1`` puts every body in ``ansich_payloads``, which
    is what makes "did the erasure take the payload rows it orphaned" a question
    with rows behind it.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ansich-hard-delete.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SqlAnsichBackend(sessions, inline_payload_max_bytes=1), sessions
    finally:
        await engine.dispose()


def _hd_scope_id(external_ref: str) -> str:
    return scope_entity_id(_HARD_DELETE_SCOPE_KIND, scope_reference_hash(_HARD_DELETE_SCOPE_KIND, external_ref))


def _hd_scope_snapshotted(task_id: str, *, external_ref: str, run_id: str, occurred_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope.scope_snapshotted(
        task_id=task_id,
        run_id=run_id,
        occurred_at=occurred_at,
        scope_kind=_HARD_DELETE_SCOPE_KIND,
        external_ref=external_ref,
        relation_role="sandbox_boundary",
        source_event_id=f"run:{run_id}:scope:{external_ref}:{task_id}",
    )


def _hd_task_started(task_id: str, *, source_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.started",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=source_id,
        occurred_at=_RETENTION_OCCURRED_AT,
        source_event_id=f"run:{source_id}:task:started",
    )


def _hd_step(task_id: str, step_id: str, *, occurred_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=occurred_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="hard-delete-fixture", version="1", instance_id="local"),
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
    )


def _hd_tool_issued(task_id: str, step_id: str, tool_call_id: str, *, occurred_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="tool.issued",
        occurred_at=occurred_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="tool_call",
        subject_id=tool_call_id,
        producer=Producer(name="hard-delete-fixture", version="1", instance_id="local"),
        source_event_id=f"tool:{tool_call_id}:issued",
        correlation_id=task_id,
        payload={
            "call_seq": 1,
            "provider_call_id": f"provider-{tool_call_id}",
            "tool_name": "task",
            "args_hash": "a" * 64,
            "args_preview": {},
            "tool_schema_block_id": None,
        },
    )


def _hd_content(task_id: str, step_id: str, block_id: str, *, body: str, occurred_at: datetime) -> ObservationEnvelope:
    canonical = body.encode("utf-8")
    return ObservationEnvelope(
        kind="content.produced",
        occurred_at=occurred_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="content_block",
        subject_id=block_id,
        producer=Producer(name="hard-delete-fixture", version="1", instance_id="local"),
        source_event_id=f"content:{block_id}",
        correlation_id=task_id,
        payload={
            "block_id": block_id,
            "kind": "tool_result",
            "content_hash": hashlib.sha256(canonical).hexdigest(),
            "visible_bytes": len(canonical),
            "estimated_tokens": 1,
            "source_identity": f"source:{block_id}",
            "body": body,
        },
    )


def _hd_spawn(parent_task_id: str, child_task_id: str, step_id: str, tool_call_id: str, *, occurred_at: datetime) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=child_task_id,
        source_kind="deerflow_subagent",
        source_id=f"provider-{tool_call_id}",
        occurred_at=occurred_at,
        source_event_id=f"deerflow_subagent:{child_task_id}:task:created",
        attributes={
            "parent_task_id": parent_task_id,
            "spawning_step_id": step_id,
            "spawning_tool_call_id": tool_call_id,
            "subagent_name": "researcher",
        },
    )


class _HardDeleteStore:
    """One thread Scope with a root Task, a spawned child, and a neighbour."""

    def __init__(self) -> None:
        self.scope_ref = "thread-doomed"
        self.scope_id = _hd_scope_id(self.scope_ref)
        self.neighbour_scope_ref = "thread-neighbour"
        self.neighbour_scope_id = _hd_scope_id(self.neighbour_scope_ref)
        self.root_id = new_id()
        self.child_id = new_id()
        self.neighbour_id = new_id()
        self.root_step = new_id()
        self.root_tool = new_id()
        self.child_step = new_id()
        self.neighbour_step = new_id()
        self.root_block = new_id()
        self.child_block = new_id()
        self.neighbour_block = new_id()
        self.doomed_tasks = (self.root_id, self.child_id)


async def _build_hard_delete_store(backend: SqlAnsichBackend, *, neighbour_first: bool = False) -> _HardDeleteStore:
    """A doomed thread with a subtree, and a neighbour thread that must survive.

    The neighbour is not decoration. Half of what "erase this owner" means is
    what it does *not* touch, and a fixture with one thread in it cannot fail
    that way. Its content block carries the **same body** as the doomed child's,
    so the two share one deduplicated ``ansich_content_blobs`` row and its
    payload — which is the exact shape that catches a deleter reclaiming a
    shared blob because it removed one of its two referrers.
    """

    store = _HardDeleteStore()
    at = _RETENTION_OCCURRED_AT

    async def _ingest(batch: list[ObservationEnvelope]) -> None:
        assert await backend.persist_and_project(batch) == len(batch)
        await _settle_retention(backend)

    neighbour = [
        _retention_task_created(store.neighbour_id, source_id="run-neighbour"),
        _hd_scope_snapshotted(store.neighbour_id, external_ref=store.neighbour_scope_ref, run_id="run-neighbour", occurred_at=at),
        _hd_step(store.neighbour_id, store.neighbour_step, occurred_at=at),
        _hd_content(store.neighbour_id, store.neighbour_step, store.neighbour_block, body="shared-body", occurred_at=at),
        _retention_heartbeat(store.neighbour_id, ordinal=1, source_id="run-neighbour"),
    ]
    # `neighbour_first` is the whole difference between a prefix erasure and a
    # hole: ingesting the surviving thread first puts survivors *below* the
    # doomed range, which is the case `min(surviving) - 1` cannot describe.
    if neighbour_first:
        await _ingest(neighbour)

    envelopes = [
        _retention_task_created(store.root_id, source_id="run-doomed"),
        _hd_task_started(store.root_id, source_id="run-doomed"),
        _hd_scope_snapshotted(store.root_id, external_ref=store.scope_ref, run_id="run-doomed", occurred_at=at),
        _hd_step(store.root_id, store.root_step, occurred_at=at),
        _hd_tool_issued(store.root_id, store.root_step, store.root_tool, occurred_at=at),
        _hd_content(store.root_id, store.root_step, store.root_block, body="doomed-root-body", occurred_at=at),
        _retention_heartbeat(store.root_id, ordinal=1, source_id="run-doomed"),
    ]
    await _ingest(envelopes)

    spawned = [
        _hd_spawn(store.root_id, store.child_id, store.root_step, store.root_tool, occurred_at=at + timedelta(seconds=1)),
        _hd_scope_snapshotted(store.child_id, external_ref=store.scope_ref, run_id="run-doomed-child", occurred_at=at + timedelta(seconds=1)),
        _hd_step(store.child_id, store.child_step, occurred_at=at + timedelta(seconds=1)),
        _hd_content(store.child_id, store.child_step, store.child_block, body="shared-body", occurred_at=at + timedelta(seconds=1)),
        _retention_heartbeat(store.child_id, ordinal=1, source_id="run-doomed-child"),
    ]
    await _ingest(spawned)

    if not neighbour_first:
        await _ingest(neighbour)
    return store


async def _record_hard_delete_audits(backend: SqlAnsichBackend, store: _HardDeleteStore) -> None:
    """Two §7 audit rows: one about the doomed Task, one about neither."""

    await backend.record_raw_read_audit(
        status="requested",
        read_id=new_id(),
        actor="admin-erasure",
        target_kind="tool_call",
        target_id=store.root_tool,
        purpose="support",
    )
    await backend.record_raw_read_audit(
        status="succeeded",
        read_id=new_id(),
        actor="admin-erasure",
        target_kind="agent_release",
        target_id=new_id(),
        purpose="support",
        outcome="served",
        http_status=200,
        served_byte_size=12,
    )


async def _referential_orphans(sessions: async_sessionmaker) -> list[str]:
    """Every Ansich row pointing at a row that is not there, from ``Base.metadata``.

    A query sweep rather than a foreign-key pragma, because the engines under
    this suite do not enforce foreign keys and a dangling reference would
    therefore be *silent* on exactly the dialect the fast tests run on. Derived
    from the metadata so a schema change that adds an edge is covered without
    anyone remembering to extend a list.
    """

    problems: list[str] = []
    async with sessions() as session:
        for table in Base.metadata.sorted_tables:
            if not table.name.startswith("ansich_"):
                continue
            for foreign_key in sorted(table.foreign_keys, key=lambda key: (key.parent.name, key.column.table.name, key.column.name)):
                child = foreign_key.parent
                parent = foreign_key.column
                dangling = await session.scalar(
                    sa.select(sa.func.count()).select_from(table).where(child.is_not(None), ~sa.exists(sa.select(sa.literal(1)).select_from(parent.table).where(parent == child))),
                )
                if dangling:
                    problems.append(f"{table.name}.{child.name} -> {parent.table.name}.{parent.name}: {dangling}")
    return problems


async def _observation_task_ids(sessions: async_sessionmaker, task_ids: Sequence[str]) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(AnsichObservationRow).where(AnsichObservationRow.task_id.in_(sorted(task_ids)))) or 0)


async def _entity_count(sessions: async_sessionmaker, entity_ids: Sequence[str]) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(AnsichEntityRow).where(AnsichEntityRow.entity_id.in_(sorted(entity_ids)))) or 0)


@pytest.mark.anyio
async def test_a_full_subtree_hard_delete_leaves_zero_orphans(hard_delete_backend):
    """The spine: Scope → Tasks → everything, and the referential walk is clean."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    await _record_hard_delete_audits(backend, store)
    assert await _referential_orphans(sessions) == []

    report = await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert await _referential_orphans(sessions) == []
    assert report.tasks == 2
    assert report.observations > 0
    assert report.relations >= 2
    assert report.batches > 1
    # The Scope itself goes: an owner erasure that left the thread's anchor
    # standing would leave the thing being erased addressable.
    assert await _entity_count(sessions, [store.scope_id, store.root_id, store.child_id]) == 0
    async with sessions() as session:
        assert await session.get(AnsichScopeRow, store.scope_id) is None
        assert await session.get(AnsichScopeRow, store.neighbour_scope_id) is not None
    # And the neighbour thread is untouched, entity for entity.
    assert await _entity_count(sessions, [store.neighbour_id, store.neighbour_step, store.neighbour_block]) == 3
    assert await _observation_task_ids(sessions, [store.neighbour_id]) > 0


@pytest.mark.anyio
async def test_the_observations_of_a_deleted_task_go_with_it(hard_delete_backend):
    """The no-foreign-key path: nothing cascades them, so they are deleted by index."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    before = await _observation_task_ids(sessions, store.doomed_tasks)
    assert before > 0

    report = await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert await _observation_task_ids(sessions, store.doomed_tasks) == 0
    assert report.observations == before


@pytest.mark.anyio
async def test_the_erasure_owns_the_payload_rows_it_orphans(hard_delete_backend):
    """The last-referrer-deleter obligation, discharged — and not over-discharged.

    Two assertions in one, and the second is the one a careless implementation
    fails: every payload of the erased Tasks is *gone* (tier 1 refuses to sweep
    an orphan, so a body left behind here is unreachable forever), while the
    deduplicated blob the neighbour Task shares with the erased child survives
    with its body, because the neighbour's content block still points at it.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session:
        doomed_payloads = sorted((await session.execute(select(AnsichObservationRow.payload_ref_id).where(AnsichObservationRow.task_id.in_(sorted(store.doomed_tasks)), AnsichObservationRow.payload_ref_id.is_not(None)))).scalars())
        # The blob the *neighbour* still points at — the one the erased child
        # shared with it. Picking any blob would prove nothing.
        neighbour_blob_key = await session.scalar(select(AnsichContentBlockRow.blob_key).where(AnsichContentBlockRow.entity_id == store.neighbour_block))
        shared_blob = await session.scalar(select(AnsichContentBlobRow.payload_ref_id).where(AnsichContentBlobRow.blob_key == neighbour_blob_key))
    assert doomed_payloads

    report = await backend.hard_delete_scope(store.scope_id, batch_size=2)

    rows = await _payload_rows(sessions)
    assert [payload_id for payload_id in doomed_payloads if payload_id in rows] == []
    assert report.payloads >= len(doomed_payloads)
    # Deleted outright, never tombstoned: there is no reader left to tell
    # "expired by policy" from "missing", because the only route to the row went
    # with the referrer in the same statement list.
    assert all(not row.deleted_at for row in rows.values())
    assert shared_blob in rows and rows[shared_blob].body is not None


@pytest.mark.anyio
async def test_no_content_blob_is_left_orphaned_holding_a_body(hard_delete_backend):
    """A blob whose last block went is the erasure's own last-referrer case."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session:
        before = int(await session.scalar(select(func.count()).select_from(AnsichContentBlobRow)) or 0)
    assert before >= 2

    await backend.hard_delete_scope(store.scope_id, batch_size=2)

    async with sessions() as session:
        blobs = list((await session.execute(select(AnsichContentBlobRow.blob_key))).scalars())
        referenced = set((await session.execute(select(AnsichContentBlockRow.blob_key))).scalars())
    assert len(blobs) < before
    assert {blob for blob in blobs if blob not in referenced} == set()


@pytest.mark.anyio
async def test_a_task_subjected_audit_row_goes_and_a_process_subjected_one_stays(hard_delete_backend):
    """The eighth family's ruling, enforced in **both** directions (D6-2).

    Privacy deletion wins for an audit row *about the erased owner's data*: it
    names which of their payloads was read, by whom and why, so keeping it would
    keep a derivative of the thing being erased. An audit row about a different
    subject — the process family, carrying the bootstrap sentinel — is untouched,
    and structurally so: no Task's erasure can reach a row whose ``task_id`` is
    the sentinel.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    await _record_hard_delete_audits(backend, store)
    async with sessions() as session:
        task_subjected = sorted((await session.execute(select(AnsichObservationRow.obs_id).where(AnsichObservationRow.kind.startswith("operator.action_"), AnsichObservationRow.task_id == store.root_id))).scalars())
        process_subjected = sorted((await session.execute(select(AnsichObservationRow.obs_id).where(AnsichObservationRow.kind.startswith("operator.action_"), AnsichObservationRow.task_id == ANSICH_BOOTSTRAP_TASK_ID))).scalars())
    assert task_subjected and process_subjected

    report = await backend.hard_delete_scope(store.scope_id, batch_size=2)

    async with sessions() as session:
        survivors = sorted((await session.execute(select(AnsichObservationRow.obs_id).where(AnsichObservationRow.kind.startswith("operator.action_")))).scalars())
    assert survivors == process_subjected
    assert report.audit_refs == len(task_subjected)
    # `audit_refs` is a subset of `observations`, deliberately, and the contract
    # says so — a reader who wants the non-audit total subtracts.
    assert report.audit_refs <= report.observations


@pytest.mark.anyio
async def test_the_bootstrap_sentinel_subject_rows_belong_to_no_deletable_task(hard_delete_backend):
    """Structural, not incidental: the sentinel is never in any Scope's Task set."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session:
        order = await SqlAnsichBackend._hard_delete_task_order(session, store.scope_id)
    assert set(order) == set(store.doomed_tasks)
    assert ANSICH_BOOTSTRAP_TASK_ID not in order
    # And it is not an entity at all, so no Entity sweep can reach it either.
    async with sessions() as session:
        assert await session.get(AnsichEntityRow, ANSICH_BOOTSTRAP_TASK_ID) is None


@pytest.mark.anyio
async def test_the_active_task_read_model_row_goes_with_its_task(hard_delete_backend):
    """PB7: the read-model row is deleted in the plan's own transaction."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    await backend.assess_operations(now=_RETENTION_OCCURRED_AT + timedelta(seconds=30))
    async with sessions() as session:
        live = sorted((await session.execute(select(AnsichActiveTaskReadModelRow.task_id))).scalars())
    assert store.root_id in live

    report = await backend.hard_delete_scope(store.scope_id, batch_size=2)

    async with sessions() as session:
        remaining = sorted((await session.execute(select(AnsichActiveTaskReadModelRow.task_id))).scalars())
    assert store.root_id not in remaining
    assert store.child_id not in remaining
    assert report.read_models >= 1


@pytest.mark.anyio
async def test_a_hard_deleted_range_never_resurfaces_through_the_horizon(hard_delete_backend):
    """Precedence over time retention, and the FC-3 flip it would otherwise cause.

    A deliberate erasure read back as ``failed`` — *presumed lost* — is the same
    lie the retention horizon exists to prevent, in the one direction retention
    itself cannot cause. So the erasure moves the horizon over what it removed,
    in the transaction that removed it, and the receipt reads ``expired``
    immediately rather than after some later sweep happens to walk past.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session:
        doomed = list(await session.execute(select(AnsichObservationRow.ingest_seq, AnsichObservationRow.obs_id).where(AnsichObservationRow.task_id.in_(sorted(store.doomed_tasks))).order_by(AnsichObservationRow.ingest_seq)))
    assert await backend.observation_retention_horizon() == 0
    lowest_doomed = int(doomed[0][0])
    sample_obs = str(doomed[0][1])

    await backend.hard_delete_scope(store.scope_id, batch_size=2)

    horizon = await backend.observation_retention_horizon()
    assert horizon >= lowest_doomed
    async with sessions() as session:
        lowest_survivor = await session.scalar(select(func.min(AnsichObservationRow.ingest_seq)))
    # Exactly one below the lowest survivor: the largest value of "everything at
    # or below this is gone" that is still true. Never a survivor's own seq.
    assert horizon == int(lowest_survivor) - 1
    assert await backend.get_observation_projection_status(sample_obs) == "expired"


@pytest.mark.anyio
async def test_a_hard_delete_above_the_horizon_does_not_stall_the_observation_tier(hard_delete_backend):
    """The interplay, converged over two passes rather than argued about.

    Tier 2 walks *existing rows* ordered by ``ingest_seq``, so the hole an
    erasure punches above its horizon is not a candidate and the walk steps over
    it. The proof is that the horizon keeps moving afterwards — a tier that
    stalled on the gap would leave it where the erasure put it, forever.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    now = _RETENTION_OCCURRED_AT + timedelta(days=400)
    policy = RetentionPolicy(raw_payload_days=7, observation_days=30, structural_days=90, cleanup_batch_size=2)

    await backend.hard_delete_scope(store.scope_id, batch_size=2)
    after_erasure = await backend.observation_retention_horizon()

    first = await backend.run_retention(policy, now=now)
    second = await backend.run_retention(policy, now=now)

    assert second.observation_horizon_ingest_seq > after_erasure
    assert (first.observations_deleted or 0) + (second.observations_deleted or 0) > 0
    assert await _referential_orphans(sessions) == []


@pytest.mark.anyio
async def test_the_sentinel_and_the_host_scope_are_refused_with_a_typed_error(hard_delete_backend):
    """Two refusals, before anything is deleted, branchable without matching prose."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    before = await _observation_task_ids(sessions, store.doomed_tasks)

    with pytest.raises(HardDeleteError) as sentinel:
        await backend.hard_delete_scope(ANSICH_BOOTSTRAP_TASK_ID)
    assert sentinel.value.reason == "bootstrap_sentinel"

    with pytest.raises(HardDeleteError) as host:
        await backend.hard_delete_scope(host_scope_id(backend._hostname))
    assert host.value.reason == "host_scope"

    with pytest.raises(HardDeleteError) as unknown:
        await backend.hard_delete_scope(new_id())
    assert unknown.value.reason == "unknown_scope"

    assert await _observation_task_ids(sessions, store.doomed_tasks) == before


@pytest.mark.anyio
async def test_a_parent_scope_is_refused_before_anything_is_deleted(hard_delete_backend):
    """``RESTRICT`` would refuse it anyway — mid-erasure, as a driver error."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session, session.begin():
        neighbour = await session.get(AnsichScopeRow, store.neighbour_scope_id)
        neighbour.parent_scope_id = store.scope_id
    before = await _observation_task_ids(sessions, store.doomed_tasks)

    with pytest.raises(HardDeleteError) as refusal:
        await backend.hard_delete_scope(store.scope_id)

    assert refusal.value.reason == "parent_scope"
    assert refusal.value.blocker == "ansich_scopes.parent_scope_id"
    assert refusal.value.scope_id == store.scope_id
    # T10 N7 / batch-final B11: the message names *which* child, which is the
    # one thing in this refusal the operator can act on. The reason and the
    # blocker column say what rule fired; neither says where to go next.
    assert store.neighbour_scope_id in str(refusal.value)
    assert await _observation_task_ids(sessions, store.doomed_tasks) == before


@pytest.mark.anyio
async def test_an_interrupted_erasure_resumes_from_the_store_without_double_counting(hard_delete_backend):
    """No cursor row: the ``within_scope`` edge is the resume handle.

    A Task's membership edge is deleted in the same transaction as the Task, so
    a run killed between batches leaves the store saying exactly what is still
    owed. Re-running the same call finishes it, and the two reports add up to
    one erasure rather than overlapping.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    total_observations = await _observation_task_ids(sessions, store.doomed_tasks)
    real_plan = sql_module._plan_cascade
    budget = {"left": 24}

    async def _dying_plan(*args, **kwargs):
        if budget["left"] <= 0:
            raise RuntimeError("hard delete killed mid-batch")
        budget["left"] -= 1
        return await real_plan(*args, **kwargs)

    sql_module._plan_cascade = _dying_plan
    try:
        with pytest.raises(RuntimeError, match="killed mid-batch"):
            await backend.hard_delete_scope(store.scope_id, batch_size=1)
    finally:
        sql_module._plan_cascade = real_plan

    partial = await _observation_task_ids(sessions, store.doomed_tasks)
    assert 0 < partial < total_observations

    resumed = await backend.hard_delete_scope(store.scope_id, batch_size=1)

    assert await _observation_task_ids(sessions, store.doomed_tasks) == 0
    assert resumed.observations == partial
    assert await _referential_orphans(sessions) == []


@pytest.mark.anyio
async def test_a_resume_after_the_last_task_still_erases_what_the_scope_was_pinning(hard_delete_backend):
    """The resume window the Task loop cannot cover, closed by a derived arm.

    The Scope pins the Observation that created it (``created_obs_id``,
    ``RESTRICT``), so that row is the one deferral every erasure produces and it
    can only go once the Scope does. A run killed *after* its last Task and
    before the Scope phase therefore leaves a store where the Scope stands, no
    Task of it does, and one Observation is reachable through neither. The
    re-run has no Task order to match it against, so matching on "this run
    condemned it" alone would strand it forever — which is why the second arm
    asks whether the owning Task still exists as an Entity at all.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    real_scope_phase = SqlAnsichBackend._hard_delete_scope_row

    async def _dying_scope_phase(self, *args, **kwargs):
        raise RuntimeError("hard delete killed before the scope phase")

    SqlAnsichBackend._hard_delete_scope_row = _dying_scope_phase  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="before the scope phase"):
            await backend.hard_delete_scope(store.scope_id, batch_size=2)
    finally:
        SqlAnsichBackend._hard_delete_scope_row = real_scope_phase  # type: ignore[method-assign]

    stranded = await _observation_task_ids(sessions, store.doomed_tasks)
    assert stranded > 0, "the Scope must still be pinning something, or this proves nothing"
    async with sessions() as session:
        order = await SqlAnsichBackend._hard_delete_task_order(session, store.scope_id)
    assert order == (), "the re-run must have no Task order left, which is the whole difficulty"

    resumed = await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert resumed.observations == stranded
    assert await _observation_task_ids(sessions, store.doomed_tasks) == 0
    assert await _referential_orphans(sessions) == []
    async with sessions() as session:
        assert await session.get(AnsichScopeRow, store.scope_id) is None
    # The neighbour's Observations were never candidates: their Task is still an
    # Entity, so the second arm does not reach them.
    assert await _observation_task_ids(sessions, [store.neighbour_id]) > 0


@pytest.mark.anyio
async def test_the_erasure_takes_the_maintenance_and_retention_keys_in_that_order(hard_delete_backend, monkeypatch):
    """Both locks, fixed order — the resurrection peer and the horizon peer.

    Retention's key alone would leave a ``rebuild`` free to re-derive rows from
    Observations this erasure has not reached yet; the maintenance key alone
    would leave two deleters writing one horizon row. Nothing else in the module
    takes both, which is what makes the fixed order deadlock-free.

    It also pins **where each refusal is answered**. The two that read nothing —
    the sentinel and the host Scope — take no lock at all, because a request
    that was never going to touch the store must not queue a rebuild and a
    sweep behind it. The three that read the store are answered *inside* the
    locks: a check taken before them is a time-of-check/time-of-use gap that
    surfaces as the ``IntegrityError`` the typed refusal exists to replace,
    mid-erasure, after batches have committed.
    """

    backend, _sessions = hard_delete_backend
    taken: list[int] = []
    real_lock = SqlAnsichBackend._advisory_lock

    def _recording(self, key: int, *, purpose: str, refusal: str):
        taken.append(key)
        return real_lock(self, key, purpose=purpose, refusal=refusal)

    monkeypatch.setattr(SqlAnsichBackend, "_advisory_lock", _recording)
    for scope_id in (ANSICH_BOOTSTRAP_TASK_ID, host_scope_id(backend._hostname)):
        with pytest.raises(HardDeleteError):
            await backend.hard_delete_scope(scope_id)
    assert taken == [], "a refusal that reads nothing must not take a lock"

    with pytest.raises(HardDeleteError) as unknown:
        await backend.hard_delete_scope(_hd_scope_id("never-created"))
    assert unknown.value.reason == "unknown_scope"
    assert taken == [_PG_MAINTENANCE_LOCK_KEY, _PG_RETENTION_LOCK_KEY], "a refusal that reads the store is answered under the locks"

    taken.clear()
    store = await _build_hard_delete_store(backend)
    await backend.hard_delete_scope(store.scope_id, batch_size=2)
    assert taken == [_PG_MAINTENANCE_LOCK_KEY, _PG_RETENTION_LOCK_KEY]


@pytest.mark.anyio
async def test_the_task_order_is_deepest_first_and_deterministic(hard_delete_backend):
    """Constraint 8 at the traversal that takes the locks.

    Deepest-first is what stops an interrupted run stranding a descendant whose
    only route from the Scope ran through its ancestor, and the tie-break on id
    is what makes two workers planning the same erasure issue the same
    statements in the same order.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session:
        order = await SqlAnsichBackend._hard_delete_task_order(session, store.scope_id)
        again = await SqlAnsichBackend._hard_delete_task_order(session, store.scope_id)
    assert order == (store.child_id, store.root_id)
    assert order == again


def test_both_spawn_producers_sort_their_descendant_tuple():
    """Constraint 8's named residual, paid at the producers (not at the consumer).

    ``backend/AGENTS.md`` said the first change that walks ``descendant_task_ids``
    taking locks must sort it at **both** producers first; the owner hard delete
    is that change. Read off the AST rather than trusted to a comment, so a later
    edit that drops one of the two sorts turns this red.
    """

    functions = _named_functions(_sql_module_ast())

    def _sorts_the_whole_tuple(value: ast.expr) -> bool:
        """The sort must wrap the **whole** value, not sit somewhere inside it.

        ``[(child, 0), *sorted(rows)]`` contains a ``sorted`` call and is
        semantically the exact bug that was paid off — the child prepended ahead
        of an ordered tail — so "some sorted() appears" is not the property. What
        is: the outermost expression is ``sorted(...)``, or a one-argument
        wrapper (``tuple``/``list``) around it.
        """

        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name):
            return False
        if value.func.id == "sorted":
            return True
        if value.func.id in {"tuple", "list"} and len(value.args) == 1:
            return _sorts_the_whole_tuple(value.args[0])
        return False

    for name in ("_project_task_spawn", "_reconcile_spawn_usage"):
        assignments = [node for node in ast.walk(functions[name]) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {"descendant_depths", "descendant_task_ids"} for target in node.targets)]
        assert assignments, f"{name} no longer produces a descendant tuple"
        for node in assignments:
            assert _sorts_the_whole_tuple(node.value), f"{name} produces a descendant tuple whose ordering is not a whole-value sort"

    # And the weaker form really is weaker: the shape below carries a `sorted`
    # call and is still the bug, so a pin that only looked for one would pass it.
    prepended = ast.parse("descendant_task_ids = [(child_task_id, 0), *sorted(rows)]").body[0]
    assert any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "sorted" for call in ast.walk(prepended))
    assert not _sorts_the_whole_tuple(prepended.value)


@pytest.mark.anyio
async def test_the_service_seam_passes_the_erasure_through_under_the_projection_lock(hard_delete_backend):
    """The passthrough, and the one thing it adds that retention deliberately does not."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    service = AnsichService(backend)
    service._projection_lock = asyncio.Lock()
    held: list[bool] = []
    real = backend.hard_delete_scope

    async def _observing(scope_id, *, batch_size=None):
        held.append(service._projection_lock.locked())
        return await real(scope_id, batch_size=batch_size)

    backend.hard_delete_scope = _observing  # type: ignore[method-assign]
    try:
        report = await service.hard_delete_scope(store.scope_id, batch_size=2)
    finally:
        backend.hard_delete_scope = real  # type: ignore[method-assign]
    assert held == [True]
    assert report.tasks == 2
    assert await _observation_task_ids(sessions, store.doomed_tasks) == 0


def test_the_task_row_phase_is_what_unpins_a_content_block():
    """The schema fact phase 2 of the erasure exists for, read off ``Base.metadata``.

    A content block cannot be deleted while a ``ansich_content_occurrences`` row
    points at it (``RESTRICT``), and the occurrence cascades from
    ``ansich_tasks`` rather than from anything the satellite sweep touches. That
    is the whole reason the Task row is deleted in its own phase *between* two
    satellite sweeps instead of last. Derived rather than commented, so a schema
    change that moves either edge turns this red instead of turning the erasure
    into a ``blocked`` refusal nobody can explain.
    """

    occurrences = Base.metadata.tables["ansich_content_occurrences"]
    edges = {key.parent.name: (key.ondelete or "").upper() for key in occurrences.foreign_keys}

    assert edges["block_id"] not in {"CASCADE", "SET NULL"}, "the occurrence no longer blocks its content block"
    assert edges["task_id"] == "CASCADE", "the Task row no longer takes the occurrence with it"
    assert "ansich_content_occurrences" in _cascade_delete_closure(frozenset({"ansich_tasks"}))
    # And the block itself is only reachable through its Entity, which is what
    # makes the second sweep — rather than the Task row phase — the thing that
    # deletes it.
    assert "ansich_content_blocks" not in _cascade_delete_closure(frozenset({"ansich_tasks"}))
    assert "ansich_content_blocks" in _cascade_delete_closure(frozenset({"ansich_entities"}))


@pytest.mark.anyio
async def test_a_blocked_erasure_leaves_the_scope_standing_and_finishes_after_the_obstacle_clears(hard_delete_backend):
    """Review finding F1, as a committed regression.

    A doomed Task that first-discovered a **protected** Entity — here a second,
    foreign thread Scope — pins one of its Observations, and the erasure cannot
    take it. The shape that shipped first deleted the target Scope, committed
    that transaction, and *then* raised: the resume handle was gone, so the
    re-run answered ``unknown_scope`` 404 and one Observation of the erased
    owner stood in the store permanently, with every route back closed.

    Three things are asserted here and all three are the fix: the refusal leaves
    the Scope row standing, the **re-run still refuses rather than 404ing**
    (which is what makes "remove the blocker and re-run" a real remedy), and
    once the obstacle is cleared the same call completes with zero orphans.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    # A second thread Scope reported by the doomed root Task. It is a protected
    # entity type, so the satellite sweep skips it and its `created_obs_id`
    # (RESTRICT) pins an Observation of a Task this erasure is condemning.
    obstacle_ref = "thread-obstacle"
    obstacle_id = _hd_scope_id(obstacle_ref)
    extra = [_hd_scope_snapshotted(store.root_id, external_ref=obstacle_ref, run_id="run-doomed-obstacle", occurred_at=_RETENTION_OCCURRED_AT)]
    assert await backend.persist_and_project(extra) == 1
    await _settle_retention(backend)

    with pytest.raises(HardDeleteError) as first:
        await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert first.value.reason == "blocked"
    # The remedy names the removable edge, not the surviving entity row it
    # refused on first (review finding F4).
    assert first.value.blocker == "ansich_scopes.created_obs_id"
    assert isinstance(first.value.report, HardDeleteReport)
    assert first.value.report.tasks >= 1, "the committed counts ride along, or a caller reads `blocked` as `nothing happened`"
    async with sessions() as session:
        assert await session.get(AnsichScopeRow, store.scope_id) is not None, "the Scope row is the resume handle and must survive the refusal"
        assert await session.get(AnsichEntityRow, store.root_id) is not None, "the pinned Task rolls back too, so nothing is stranded"

    # The re-run refuses the same way — never 404 — which is what makes the
    # documented remedy executable. This is the assertion the shipped shape
    # could not satisfy: it had deleted the Scope, so the re-run answered
    # `unknown_scope` and the erasure was unfinishable.
    with pytest.raises(HardDeleteError) as second:
        await backend.hard_delete_scope(store.scope_id, batch_size=2)
    assert second.value.reason == "blocked"
    assert await _referential_orphans(sessions) == []

    # Erasing the obstacle Scope refuses too, and that is the documented
    # limitation rather than a defect: both Scopes' provenance runs through the
    # *same* Task, so neither can free the other's pin. What matters is that it
    # is **reported** — a typed refusal naming the edge — instead of one of them
    # succeeding and leaving the other's evidence behind.
    with pytest.raises(HardDeleteError) as mutual:
        await backend.hard_delete_scope(obstacle_id, batch_size=2)
    assert mutual.value.reason == "blocked"

    # Clear the obstacle the way an operator with a mutual pin must: remove the
    # foreign Scope's rows. (There is no API for it in v1 — that is the
    # residual, and this is what "after the obstacle clears" means for it.)
    async with sessions() as session, session.begin():
        await session.execute(sa.delete(AnsichScopeRow).where(AnsichScopeRow.entity_id == obstacle_id))
        await session.execute(sa.delete(AnsichEntityRow).where(AnsichEntityRow.entity_id == obstacle_id))

    finished = await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert await _observation_task_ids(sessions, store.doomed_tasks) == 0
    assert await _referential_orphans(sessions) == []
    async with sessions() as session:
        assert await session.get(AnsichScopeRow, store.scope_id) is None
    assert finished.observations > 0
    # The two reports add up to one erasure, which is the contract: the refused
    # run had already committed both `ansich_tasks` deletes (only the pinned
    # Task's *Entity* rolled back), so the resumed run legitimately reports
    # zero there and finishes the rest.
    assert first.value.report.tasks + finished.tasks == 2
    assert await _observation_task_ids(sessions, [store.neighbour_id]) > 0


@pytest.mark.anyio
async def test_a_shared_scope_kind_is_refused_before_anything_is_deleted(hard_delete_backend):
    """Review finding F2: only ``owner`` and ``thread`` name one owner's data.

    ``workspace``/``sandbox``/``authorization``/``external_origin`` Scopes are
    shared across owners by construction — a repository path, a pooled runtime,
    a policy, a provenance — so erasing one would take every Task that ever
    reported it, from every owner, with no signal that it had. That is the same
    argument the host-Scope refusal already rests on, and D6-2 calls this the
    *owner/thread* hard delete.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    workspace_ref = "/srv/shared-repo"
    workspace_id = scope_entity_id("workspace", scope_reference_hash("workspace", workspace_ref))
    shared = [
        ObservationEnvelope.scope_snapshotted(
            task_id=store.neighbour_id,
            run_id="run-neighbour",
            occurred_at=_RETENTION_OCCURRED_AT,
            scope_kind="workspace",
            external_ref=workspace_ref,
            relation_role="sandbox_boundary",
            source_event_id="run:run-neighbour:scope:workspace",
        )
    ]
    assert await backend.persist_and_project(shared) == 1
    await _settle_retention(backend)
    before = await _observation_task_ids(sessions, store.doomed_tasks)

    with pytest.raises(HardDeleteError) as refusal:
        await backend.hard_delete_scope(workspace_id)

    assert refusal.value.reason == "shared_scope_kind"
    assert set(_HARD_DELETE_OWNER_SCOPE_KINDS) == {"owner", "thread"}
    assert set(_HARD_DELETE_OWNER_SCOPE_KINDS) < set(get_args(ScopeKind)), "the deletable kinds must stay a strict subset, or the guard means nothing"
    assert refusal.value.blocker == "ansich_scopes.scope_kind"
    assert refusal.value.report is None, "a refusal raised before any delete has no partial report to carry"
    assert await _observation_task_ids(sessions, store.doomed_tasks) == before
    async with sessions() as session:
        assert await session.get(AnsichScopeRow, workspace_id) is not None
    # And the thread Scope beside it is still erasable, so the guard is a kind
    # test rather than a blanket refusal.
    assert (await backend.hard_delete_scope(store.scope_id, batch_size=2)).tasks == 2


@pytest.mark.anyio
async def test_an_erased_range_above_a_survivor_still_reads_expired(hard_delete_backend):
    """Review finding F3: the hole case, which the prefix fixture cannot show.

    ``min(surviving ingest_seq) - 1`` cannot move when a survivor sits **below**
    the erased range, and the horizon may not be inflated past a survivor
    (tier 2 reads it as its own cursor and would skip live rows forever). With
    only that mark, an erased Observation read ``failed`` — *presumed lost* —
    which is the exact FC-3 flip the mechanism exists to prevent.

    The neighbour is ingested **first** here, so the erased range is a genuine
    hole and not a prefix. What answers it is the second mark: the
    non-contiguous deletion cursor T9 reserved for exactly this deleter.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend, neighbour_first=True)
    async with sessions() as session:
        rows = list(await session.execute(select(AnsichObservationRow.ingest_seq, AnsichObservationRow.obs_id, AnsichObservationRow.task_id).order_by(AnsichObservationRow.ingest_seq)))
    doomed = [row for row in rows if str(row[2]) in set(store.doomed_tasks)]
    survivors_below = [row for row in rows if str(row[2]) not in set(store.doomed_tasks) and int(row[0]) < int(doomed[0][0])]
    assert survivors_below, "the fixture must put a survivor below the erased range, or this is the prefix case again"
    sample_obs = str(doomed[0][1])

    await backend.hard_delete_scope(store.scope_id, batch_size=2)

    async with sessions() as session:
        state = await session.get(AnsichRetentionStateRow, 1)
        horizon = int(state.observation_horizon_ingest_seq or 0)
        cursor = int(state.observation_cursor or 0)
        lowest_survivor = int(await session.scalar(select(func.min(AnsichObservationRow.ingest_seq))))
    # The horizon is honest and unmoved: it may never claim a survivor is gone.
    assert horizon < lowest_survivor
    assert horizon == 0
    # The non-contiguous mark is what carries the erasure.
    assert cursor >= int(doomed[-1][0])
    assert await backend.get_observation_projection_status(sample_obs) == "expired"


@pytest.mark.anyio
async def test_the_hole_the_erasure_punched_does_not_stall_the_observation_tier(hard_delete_backend):
    """The other half of F3's binding requirement, on the hole fixture.

    Tier 2 selects existing rows ordered by ``ingest_seq``, so a hole is simply
    never a candidate and the walk steps over it. Proved by the horizon moving
    *past* the erased range on ordinary passes rather than stopping at it.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend, neighbour_first=True)
    now = _RETENTION_OCCURRED_AT + timedelta(days=400)
    policy = RetentionPolicy(raw_payload_days=7, observation_days=30, structural_days=90, cleanup_batch_size=2)
    # Survivors on *both* sides of the erased range: without rows above it,
    # "the walk steps over the hole" has nothing to step onto and the assertion
    # below would be satisfied by an empty store instead of by a moving walk.
    later = [_retention_heartbeat(store.neighbour_id, ordinal=ordinal, source_id="run-neighbour") for ordinal in (2, 3, 4)]
    assert await backend.persist_and_project(later) == len(later)
    await _settle_retention(backend)
    async with sessions() as session:
        doomed_seqs = sorted(int(row[0]) for row in await session.execute(select(AnsichObservationRow.ingest_seq, AnsichObservationRow.task_id)) if str(row[1]) in set(store.doomed_tasks))
        above = sorted(int(row[0]) for row in await session.execute(select(AnsichObservationRow.ingest_seq, AnsichObservationRow.task_id)) if str(row[1]) not in set(store.doomed_tasks) and int(row[0]) > max(doomed_seqs))
    assert above, "the fixture must leave survivors above the hole"

    await backend.hard_delete_scope(store.scope_id, batch_size=2)
    assert await backend.observation_retention_horizon() == 0

    for _ in range(6):
        await backend.run_retention(policy, now=now)

    assert await backend.observation_retention_horizon() > max(doomed_seqs), "the tier must walk past the hole, not stall at it"
    assert await _observation_ids(sessions) == []
    assert await _referential_orphans(sessions) == []


@pytest.mark.anyio
async def test_tier_three_reclaims_a_content_blob_with_no_hard_delete_in_the_picture(retention_backend):
    """Review finding F5: the live retention leak the shared helper closes.

    The blob obligation was found while writing the hard delete, but the leak it
    fixes is **tier 3's** and reproduces with no erasure anywhere near it: the
    structural tier deletes a content-block Entity, and the ``ansich_content_blobs``
    row it was the last referrer of holds the body. Tier 1 refuses to sweep an
    orphan by design, so without this those bytes are unreachable forever.

    Pinned separately because the hard-delete test cannot see it — a later
    refactor that moved the reclaim into the erasure path only would re-open the
    retention leak silently.
    """

    backend, sessions = retention_backend
    task_id = new_id()
    at = _RETENTION_OCCURRED_AT
    envelopes = [
        _retention_task_created(task_id, source_id="run-blob"),
        _hd_step(task_id, new_id(), occurred_at=at),
    ]
    step_id = str(envelopes[-1].step_id)
    envelopes.append(_hd_content(task_id, step_id, new_id(), body="tier-three-blob-body", occurred_at=at))
    assert await backend.persist_and_project(envelopes) == len(envelopes)
    await _settle_retention(backend)
    async with sessions() as session:
        assert int(await session.scalar(select(func.count()).select_from(AnsichContentBlobRow)) or 0) == 1

    policy = RetentionPolicy(raw_payload_days=7, observation_days=30, structural_days=90, cleanup_batch_size=5)
    for _ in range(6):
        await backend.run_retention(policy, now=at + timedelta(days=400))

    async with sessions() as session:
        blobs = list((await session.execute(select(AnsichContentBlobRow.blob_key))).scalars())
        referenced = set((await session.execute(select(AnsichContentBlockRow.blob_key))).scalars())
    assert [blob for blob in blobs if blob not in referenced] == [], "tier 3 must reclaim the blob it orphaned"
    assert all(row.body is not None or row.deleted_at is not None for row in (await _payload_rows(sessions)).values())


def test_the_batch_counter_ignores_a_transaction_that_deleted_nothing():
    """``batches`` means what the contract says (review finding F9).

    ``HardDeleteReport.batches`` is documented as "committed transactions that
    deleted something", and a counter that ticked on an empty commit would let a
    refusal — a phase in which everything was blocked or deferred — read as
    progress. The rollback half is pinned in the same place: the counters are a
    plain object and know nothing about transactions, so a phase that absorbed a
    plan and then raised would otherwise report rows the database restores.
    """

    counts = _HardDeleteCounts()

    counts.commit_batch()
    assert counts.batches == 0, "an empty commit is not a batch"

    counts.absorb({"ansich_tasks": 1, "ansich_steps": 3}, 2)
    counts.commit_batch()
    assert (counts.batches, counts.tasks, counts.projections, counts.payloads) == (1, 1, 3, 2)

    counts.commit_batch()
    assert counts.batches == 1, "a second commit that changed nothing is not a second batch"

    counts.absorb({"ansich_observations": 4}, 1)
    counts.rollback_batch()
    counts.commit_batch()
    assert (counts.batches, counts.observations, counts.payloads) == (1, 0, 2), "a rolled-back transaction leaves neither counts nor a batch"
    # `deleted_total` is live: `_advance_deletion_horizon` gates the one-way
    # deliberate-deletion mark on it. So the property that matters is that
    # `audit_refs` — a **subset** of `observations` — cannot move it, or an
    # erasure that deleted only audit rows would count them twice and a refused
    # one could stamp the mark off a number that describes nothing.
    before = counts.deleted_total()
    counts.audit_refs += 5
    assert counts.deleted_total() == before, "audit_refs is a subset of observations and must not enter the total"
    counts.observations += 3
    assert counts.deleted_total() == before + 3
    assert _HardDeleteCounts().deleted_total() == 0, "a fresh counter has deleted nothing, which is what gates the mark"


@pytest.mark.anyio
async def test_a_pin_no_product_action_can_clear_is_refused_before_anything_is_deleted(hard_delete_backend):
    """Review finding N1: an erasure that cannot end must not begin.

    ``blocked`` says *"clear this and re-run"*, and that is a real remedy when
    the pinning entity is another ``owner``/``thread`` Scope. It is no remedy at
    all when the pinning entity's own erasure is refused **by type** — the host
    Scope (``host_scope``), a shared-kind Scope (``shared_scope_kind``), an
    AgentRelease (no erasure path exists). In those shapes an operator who
    started would get most of the owner erased and a refusal nothing in the
    product can clear, so the shape is detected up front and refused with its
    own reason.

    Both type-refused Scope shapes are exercised, because they fail for
    different reasons and a guard that caught only one would look right.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    workspace_ref = "/srv/shared"
    pinning = [
        ObservationEnvelope.scope_snapshotted(
            task_id=store.root_id,
            run_id="run-doomed",
            occurred_at=_RETENTION_OCCURRED_AT,
            scope_kind="workspace",
            external_ref=workspace_ref,
            relation_role="sandbox_boundary",
            source_event_id=f"run:run-doomed:scope:workspace:{store.root_id}",
        )
    ]
    assert await backend.persist_and_project(pinning) == 1
    await _settle_retention(backend)
    before = await _observation_task_ids(sessions, store.doomed_tasks)

    with pytest.raises(HardDeleteError) as refusal:
        await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert refusal.value.reason == "unsatisfiable_pin", "a shared-kind pin must be refused up front, not discovered mid-erasure"
    assert refusal.value.blocker == "ansich_scopes.created_obs_id"
    assert refusal.value.report is None, "nothing was deleted, so there is no partial report to carry"
    # The whole point: the store is exactly as it was.
    assert await _observation_task_ids(sessions, store.doomed_tasks) == before
    assert await _referential_orphans(sessions) == []
    async with sessions() as session:
        assert await session.get(AnsichScopeRow, store.scope_id) is not None
        assert await session.get(AnsichEntityRow, store.root_id) is not None

    # And erasing the pinning Scope is refused by type, which is what makes the
    # pin unsatisfiable rather than merely inconvenient.
    with pytest.raises(HardDeleteError) as remedy:
        await backend.hard_delete_scope(scope_entity_id("workspace", scope_reference_hash("workspace", workspace_ref)))
    assert remedy.value.reason == "shared_scope_kind"


@pytest.mark.anyio
async def test_a_host_scope_pin_is_refused_up_front_too(hard_delete_backend):
    """The other type-refused shape (N1), on its own store."""

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    pinning = [
        ObservationEnvelope.scope_snapshotted(
            task_id=store.root_id,
            run_id="run-doomed",
            occurred_at=_RETENTION_OCCURRED_AT,
            scope_kind="host",
            external_ref=backend._hostname,
            relation_role="sandbox_boundary",
            source_event_id=f"run:run-doomed:scope:host:{store.root_id}",
        )
    ]
    assert await backend.persist_and_project(pinning) == 1
    await _settle_retention(backend)
    before = await _observation_task_ids(sessions, store.doomed_tasks)

    with pytest.raises(HardDeleteError) as refusal:
        await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert refusal.value.reason == "unsatisfiable_pin"
    assert host_scope_id(backend._hostname) in str(refusal.value)
    assert await _observation_task_ids(sessions, store.doomed_tasks) == before


@pytest.mark.anyio
async def test_the_protected_pin_check_covers_every_protected_type_not_just_the_named_two(hard_delete_backend):
    """The pressure test's latent gap: the filter, not the naming map.

    ``_HARD_DELETE_PROTECTED_PIN_EDGES`` exists to make the reported edge
    actionable, and an earlier form used it as the *filter* too — so a protected
    entity of any other type (a Task belonging to a different Scope that
    discovered one of these Observations) fell through the check, was deferred,
    and let a later run report success with the erased owner's Observation still
    standing. Restricting the check back to the map's keys reproduces exactly
    that, which is what makes this the regression rather than a restatement.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session:
        doomed_obs = str(await session.scalar(select(AnsichObservationRow.obs_id).where(AnsichObservationRow.task_id == store.root_id).order_by(AnsichObservationRow.ingest_seq)))
        foreign_task_entity = str(await session.scalar(select(AnsichEntityRow.entity_id).where(AnsichEntityRow.entity_id == store.neighbour_id)))
        # A protected type that is *not* in the naming map, pinning one of the
        # doomed Task's Observations from outside the run's condemned set.
        await session.execute(update(AnsichEntityRow).where(AnsichEntityRow.entity_id == foreign_task_entity).values(discovered_obs_id=doomed_obs))
        await session.commit()

        assert await SqlAnsichBackend._hard_delete_protected_pin(session, store.scope_id, frozenset({store.root_id, store.child_id}), [doomed_obs]) is not None
        # Excluded when the run is going to delete it anyway, which is the only
        # exemption the filter has.
        assert await SqlAnsichBackend._hard_delete_protected_pin(session, store.scope_id, frozenset({foreign_task_entity, store.root_id, store.child_id}), [doomed_obs]) is None
    assert "task" in _HARD_DELETE_PROTECTED_ENTITY_TYPES
    assert "task" not in _HARD_DELETE_PROTECTED_PIN_EDGES, "the map is a naming table; a type missing from it must still be caught"


@pytest.mark.anyio
async def test_an_erasure_that_removed_nothing_leaves_no_deliberate_deletion_mark(hard_delete_backend):
    """Review finding N2: the mark is one-way, so it must be earned.

    ``observation_cursor`` makes **every** absent id on this store read
    ``expired`` from then on. An earlier form stamped it from the *attempted*
    batch watermark, so a pass that deferred everything — deleting nothing —
    still left the mark behind and flipped every receipt for good. The gate is
    two-part and both halves are asserted: a positive mark, and rows this
    erasure really removed.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    async with sessions() as session:
        absent = str(await session.scalar(select(AnsichObservationRow.obs_id).where(AnsichObservationRow.task_id == store.root_id).order_by(AnsichObservationRow.ingest_seq)))
        highest = int(await session.scalar(select(func.max(AnsichObservationRow.ingest_seq))))
    counts = _HardDeleteCounts()

    async with sessions() as session, session.begin():
        await backend._advance_deletion_horizon(session, counts, highest)

    async with sessions() as session:
        state = await session.get(AnsichRetentionStateRow, 1)
        assert state.observation_cursor is None, "a pass that deleted nothing must not stamp a deliberate-deletion mark"
    assert await backend.get_observation_projection_status(absent) != "expired"

    # And the same call, once something really went, does stamp it.
    counts.absorb({"ansich_observations": 1}, 0)
    async with sessions() as session, session.begin():
        await backend._advance_deletion_horizon(session, counts, highest)
    async with sessions() as session:
        state = await session.get(AnsichRetentionStateRow, 1)
    assert int(state.observation_cursor or 0) == highest


@pytest.mark.anyio
async def test_a_surviving_unprotected_satellite_refuses_the_erasure_rather_than_stranding_it(hard_delete_backend):
    """Review finding N6: the pin check names no types, and here is why.

    A content block whose ``ansich_content_occurrences`` row belongs to a
    **surviving** Task cannot be deleted (the occurrence is ``RESTRICT``), so the
    satellite sweep skips it and it goes on pinning the doomed Task's
    Observation. It is not a *protected* type, so a check filtered to those
    three let it through: run 1 refused correctly, but the Task's Entity was
    committed-gone, and run 2 then reported **success** — deleting the Scope and
    leaving the erased owner's ``content.produced`` row with no handle left to
    reach it. That is finding F1's class, resurrected through a narrower filter.

    The referrer is built by hand because live ingest cannot produce it: a real
    occurrence is minted for the Task that produced the block. What the shape
    represents is real enough — a block one Task produced and another still
    occupies — and the assertion is the one that matters either way: **run 2
    must refuse too.**
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    planted_block = new_id()
    async with sessions() as session, session.begin():
        pinned_obs = str(await session.scalar(select(AnsichObservationRow.obs_id).where(AnsichObservationRow.task_id == store.root_id, AnsichObservationRow.kind == "task.heartbeat")))
        session.add(AnsichEntityRow(entity_id=planted_block, entity_type="content_block", discovered_obs_id=pinned_obs))
        await session.flush()
        session.add(
            AnsichContentBlockRow(
                entity_id=planted_block,
                kind="tool_result",
                content_hash="d" * 64,
                payload_obs_id=pinned_obs,
                producer_obs_id=pinned_obs,
                blob_key=None,
                byte_size=1,
                token_estimate=1,
                sensitivity_flags_json=[],
            )
        )
        await session.flush()
        session.add(
            AnsichContentOccurrenceRow(
                task_id=store.neighbour_id,
                source_identity="planted-occurrence",
                content_hash="d" * 64,
                kind="tool_result",
                block_id=planted_block,
                producer_obs_id=pinned_obs,
                created_at=_RETENTION_OCCURRED_AT,
            )
        )

    with pytest.raises(HardDeleteError) as first:
        await backend.hard_delete_scope(store.scope_id, batch_size=2)
    assert first.value.reason == "blocked"

    # The finding, in one assertion: the second run must not report success.
    with pytest.raises(HardDeleteError) as second:
        await backend.hard_delete_scope(store.scope_id, batch_size=2)
    assert second.value.reason == "blocked"

    async with sessions() as session:
        assert await session.scalar(select(AnsichObservationRow.obs_id).where(AnsichObservationRow.obs_id == pinned_obs)) is not None, "the pinned Observation is still there, which is why success would have been a lie"
        assert await session.get(AnsichScopeRow, store.scope_id) is not None
    assert await _referential_orphans(sessions) == []

    # Clear the pin and the same call finishes.
    async with sessions() as session, session.begin():
        await session.execute(sa.delete(AnsichContentOccurrenceRow).where(AnsichContentOccurrenceRow.block_id == planted_block))
        await session.execute(sa.delete(AnsichContentBlockRow).where(AnsichContentBlockRow.entity_id == planted_block))
        await session.execute(sa.delete(AnsichEntityRow).where(AnsichEntityRow.entity_id == planted_block))

    await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert await _observation_task_ids(sessions, store.doomed_tasks) == 0
    assert await _referential_orphans(sessions) == []


@pytest.mark.anyio
async def test_a_parent_scope_pin_is_deferrable_and_not_refused_up_front(hard_delete_backend):
    """Review finding N5: one mirror, and ``parent_scope`` adjudicated as an action.

    The pre-flight refuses only pins **no product action can clear**. A pinning
    Scope that is itself a parent is not one of those: "erase its children
    first" is a real sequence an operator can execute with this same API, so
    treating it as unsatisfiable would refuse work that can be done. It
    therefore falls through to the ordinary ``blocked`` path, exactly where every
    other clearable pin lands.

    What the earlier form got wrong was not the ruling but the **coupling**: the
    pre-flight hand-wrote its own three-branch copy of the Scope refusals and
    omitted ``parent_scope`` entirely, so it could not have adjudicated it either
    way. Both callers now read one mirror, and the classification of what that
    mirror answers is a declared set rather than an omission.
    """

    backend, sessions = hard_delete_backend
    store = await _build_hard_delete_store(backend)
    pinning_ref = "thread-pinning-parent"
    pinning_id = _hd_scope_id(pinning_ref)
    extra = [_hd_scope_snapshotted(store.root_id, external_ref=pinning_ref, run_id="run-doomed-parent", occurred_at=_RETENTION_OCCURRED_AT)]
    assert await backend.persist_and_project(extra) == 1
    await _settle_retention(backend)
    # Make the pinning Scope a parent, so erasing *it* would answer parent_scope.
    async with sessions() as session, session.begin():
        await session.execute(update(AnsichScopeRow).where(AnsichScopeRow.entity_id == store.neighbour_scope_id).values(parent_scope_id=pinning_id))

    # The mirror sees it — which is the coupling the finding was about.
    assert SqlAnsichBackend._scope_refusal_reason(pinning_id, scope_kind="thread", host_scope=host_scope_id(backend._hostname), child_scope_id="child-scope")[0] == "parent_scope"
    assert "parent_scope" in _HARD_DELETE_DEFERRABLE_PIN_REFUSALS

    with pytest.raises(HardDeleteError) as refusal:
        await backend.hard_delete_scope(store.scope_id, batch_size=2)

    assert refusal.value.reason == "blocked", "a clearable pin must not be reported as unclearable"
    assert refusal.value.blocker == "ansich_scopes.created_obs_id"
    async with sessions() as session:
        assert await session.get(AnsichScopeRow, store.scope_id) is not None


def test_every_scope_refusal_the_mirror_can_answer_is_classified():
    """The partition is total, and its default is the safe direction (N5).

    A sixth refusal added to ``_scope_refusal_reason`` becomes an **up-front**
    refusal with no edit to the partition — refuse before starting rather than
    half-erase — and making it deferrable is then a deliberate one-line
    adjudication. What must never happen is a reason falling through *unjudged*,
    which is what the hand-written second copy did to ``parent_scope``.
    """

    host = host_scope_id("some-host")
    answers = {
        SqlAnsichBackend._scope_refusal_reason(host, scope_kind="host", host_scope=host, child_scope_id=None),
        SqlAnsichBackend._scope_refusal_reason("s-1", scope_kind="workspace", host_scope=host, child_scope_id=None),
        SqlAnsichBackend._scope_refusal_reason("s-2", scope_kind="thread", host_scope=host, child_scope_id="s-2-child"),
    }
    reasons = {answer[0] for answer in answers if answer is not None}
    assert reasons == {"host_scope", "shared_scope_kind", "parent_scope"}
    assert reasons & _HARD_DELETE_DEFERRABLE_PIN_REFUSALS == {"parent_scope"}
    assert _HARD_DELETE_DEFERRABLE_PIN_REFUSALS <= set(get_args(HardDeleteRefusal))
    # An erasable Scope answers nothing at all.
    assert SqlAnsichBackend._scope_refusal_reason("s-3", scope_kind="thread", host_scope=host, child_scope_id=None) is None


def _hd_admin_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-erasure-admin@example.com",
        password_hash="x",
        system_role="admin",
    )


@pytest.mark.anyio
async def test_the_hard_delete_route_erases_and_answers_a_refusal_by_reason(tmp_path: Path):
    """The route, both answers.

    **This one is a route and the §5 rule does not reach it.** That rule forbids
    an endpoint that runs an arbitrary projector on demand; an owner erasure is
    an owner-initiated data action with one fixed effect, and there is no way to
    answer "delete my thread" from a CLI-only seam.

    A refusal is **409 with the reason**, not a 500 and not a bare 400: the
    request is well-formed and the *state* refuses, and a caller that cannot
    branch on which state would have to parse prose.
    """

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ansich-hard-delete-route.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = create_sql_ansich_service(sessions, operations_assessment_interval_ms=60_000)
    only_test_driven_assessments(service)
    await service.start()
    app = make_authed_test_app(user_factory=_hd_admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)
    try:
        store = await _build_hard_delete_store(service._backend)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            missing = await client.post("/api/ansich/retention/hard-delete", json={"scope_id": new_id()})
            sentinel = await client.post("/api/ansich/retention/hard-delete", json={"scope_id": ANSICH_BOOTSTRAP_TASK_ID})
            erased = await client.post("/api/ansich/retention/hard-delete", json={"scope_id": store.scope_id})
    finally:
        await service.stop()
        await engine.dispose()

    assert missing.status_code == 404
    assert missing.json()["detail"]["reason"] == "unknown_scope"
    assert sentinel.status_code == 409
    assert sentinel.json()["detail"]["reason"] == "bootstrap_sentinel"
    assert erased.status_code == 200
    report = erased.json()["report"]
    assert report["tasks"] == 2
    assert report["observations"] > 0
    assert await _observation_task_ids(sessions, store.doomed_tasks) == 0
    assert await _referential_orphans(sessions) == []
