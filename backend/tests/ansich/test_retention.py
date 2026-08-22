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
import importlib
import inspect
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
import sqlalchemy as sa
import yaml
from alembic import command as alembic_command
from ansich import ObservationEnvelope, RetentionPolicy, new_id
from ansich.errors import PayloadExpiredError
from ansich.evaluation import EvaluationProjectionStatus
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

# Pre-import models so ``Base.metadata`` carries the DeerFlow tables too.
import deerflow.persistence.models  # noqa: F401
from deerflow.ansich import retention_policy_from_config
from deerflow.ansich.persistence import sql as sql_module
from deerflow.ansich.persistence.models import (
    AnsichActiveVersionRow,
    AnsichAgentReleaseRow,
    AnsichContentBlobRow,
    AnsichEntityRow,
    AnsichObservationRow,
    AnsichPayloadRow,
    AnsichProjectionJobRow,
    AnsichRetentionStateRow,
)
from deerflow.ansich.persistence.sql import (
    _PAYLOAD_REFERRER_TIERS,
    _PG_MAINTENANCE_LOCK_KEY,
    _PG_RETENTION_LOCK_KEY,
    SqlAnsichBackend,
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
    # Tiers 2 and 3 did not run in this build, and the report says so with
    # `None` rather than lying about an empty sweep.
    assert report.observations_deleted is None
    assert report.structural_deleted is None

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

    # A year on, and still not a candidate.
    report = await backend.run_retention(_POLICY, now=_RETENTION_OCCURRED_AT + timedelta(days=365))

    payloads = await _payload_rows(sessions)
    assert payloads["manifest-payload"].body == b"{}"
    assert payloads["manifest-payload"].deleted_at is None
    assert report.payload_tombstoned == 0


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

    Three write shapes are refused: constructing a job row, passing one to an
    ``insert``, and adding one to a session. Reads are untouched — the payload
    tier's in-flight guard genuinely has to look at ``ansich_projection_jobs``,
    and a pin that forbade mentioning the table would forbid the guard that
    keeps a projector from finding an empty body.
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
            if isinstance(target, ast.Name) and target.id in _INSERT_CALLS and mentions:
                offenders.append(f"{name}: inserts into {sorted(mentions)}")
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
