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

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from alembic import command as alembic_command
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

# Pre-import models so ``Base.metadata`` carries the DeerFlow tables too.
import deerflow.persistence.models  # noqa: F401
from deerflow.ansich.persistence.models import (
    AnsichActiveVersionRow,
    AnsichObservationRow,
    AnsichPayloadRow,
    AnsichRetentionStateRow,
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
            )
        )
        session.commit()

    with Session(engine) as session:
        row = session.execute(select(AnsichActiveVersionRow)).scalar_one()
        assert (row.component_kind, row.component_name) == ("resolver", "ansich-default")
        assert row.active_version == "2.0.0"
        assert row.activated_by == "operator@example.com"
        assert row.audit_obs_id == "obs-1"


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
