"""SQL storage tests for the Phase 10 evaluation projections."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from ansich import (
    AnsichService,
    EvaluationRecord,
    NamedVersion,
    ObservationEnvelope,
    Producer,
    ScoreScale,
    build_evaluation_observation,
    new_id,
)
from ansich.release import AgentRuntimeDescriptor, RuntimeBuildDescriptor, build_agent_release
from sqlalchemy import create_engine, event, func, inspect, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import (
    AnsichBeliefAssertionRow,
    AnsichCurrentBeliefRow,
    AnsichEvaluationIndexRow,
    AnsichObservationRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichReleaseQualityStatsRow,
    AnsichTaskAgentReleaseRow,
)
from deerflow.persistence.base import Base

EVALUATION_REVISION = "0023_ansich_evaluations"
PREVIOUS_REVISION = "0022_ansich_assessor_deadline"
EVALUATION_TABLES = {"ansich_evaluation_index", "ansich_release_quality_stats"}

_OCCURRED_AT = datetime(2026, 8, 18, 9, tzinfo=UTC)
_ASSESSOR = NamedVersion(name="ansich-benchmark-runner", version="1.0.0")
_UNIT_SCALE = ScoreScale(min=0.0, max=1.0, higher_is_better=True)


def _alembic_config(database_path: Path) -> AlembicConfig:
    backend_root = Path(__file__).resolve().parents[2]
    config = AlembicConfig(str(backend_root / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    # The Alembic env only applies process-wide logging.fileConfig when this
    # remains set; the integration test must not disable loggers used later.
    config.config_file_name = None
    return config


def _sqlite_schema(database_path: Path) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]], str]:
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        database_inspector = inspect(engine)
        table_names = set(database_inspector.get_table_names())
        columns = {table: {column["name"] for column in database_inspector.get_columns(table)} for table in EVALUATION_TABLES & table_names}
        indexes = {table: {index["name"] for index in database_inspector.get_indexes(table)} for table in EVALUATION_TABLES & table_names}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()
    return table_names, columns, indexes, revision


def test_evaluation_models_compile_with_postgresql_constraints_and_indexes() -> None:
    dialect = postgresql.dialect()
    ddl = {model.__tablename__: str(CreateTable(model.__table__).compile(dialect=dialect)) for model in (AnsichEvaluationIndexRow, AnsichReleaseQualityStatsRow)}

    assert "PRIMARY KEY (evaluation_obs_id)" in ddl["ansich_evaluation_index"]
    assert "FOREIGN KEY(evaluation_obs_id) REFERENCES ansich_observations (obs_id) ON DELETE CASCADE" in ddl["ansich_evaluation_index"]
    assert "score FLOAT" in ddl["ansich_evaluation_index"]
    assert "scale_higher_is_better BOOLEAN" in ddl["ansich_evaluation_index"]
    assert "occurred_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl["ansich_evaluation_index"]

    assert "PRIMARY KEY (release_id, cohort_key, dimension)" in ddl["ansich_release_quality_stats"]
    assert "FOREIGN KEY(release_id) REFERENCES ansich_entities (entity_id) ON DELETE CASCADE" in ddl["ansich_release_quality_stats"]
    assert "assessed_count INTEGER NOT NULL" in ddl["ansich_release_quality_stats"]
    assert "score_sum FLOAT" in ddl["ansich_release_quality_stats"]
    # Scale polarity is part of scale identity: comparing two cells on range
    # alone would compare a higher-is-better mean against a lower-is-better one.
    assert "scale_higher_is_better BOOLEAN" in ddl["ansich_release_quality_stats"]
    assert "as_of TIMESTAMP WITH TIME ZONE NOT NULL" in ddl["ansich_release_quality_stats"]

    assert {index.name for index in AnsichEvaluationIndexRow.__table__.indexes} == {
        "ix_ansich_evaluation_subject_dimension",
        "ix_ansich_evaluation_suite_case",
        "ix_ansich_evaluation_task",
    }
    # The primary key is exactly (release_id, cohort_key, dimension), so a separate
    # index over that same tuple would be pure write amplification.
    assert AnsichReleaseQualityStatsRow.__table__.indexes == set()
    assert "ix_ansich_release_quality_cohort" not in ddl["ansich_release_quality_stats"]


def test_evaluation_migration_upgrades_sqlite(tmp_path) -> None:
    database_path = tmp_path / "ansich-evaluations-migration.db"
    config = _alembic_config(database_path)

    alembic_command.upgrade(config, "head")

    table_names, columns, indexes, revision = _sqlite_schema(database_path)

    assert EVALUATION_TABLES <= table_names
    assert columns["ansich_evaluation_index"] == {column.name for column in AnsichEvaluationIndexRow.__table__.columns}
    assert columns["ansich_release_quality_stats"] == {column.name for column in AnsichReleaseQualityStatsRow.__table__.columns}
    assert indexes["ansich_evaluation_index"] == {index.name for index in AnsichEvaluationIndexRow.__table__.indexes}
    assert "ix_ansich_release_quality_cohort" not in indexes["ansich_release_quality_stats"]
    assert revision == EVALUATION_REVISION
    assert len(revision) <= 32


def test_evaluation_migration_is_idempotent_on_existing_tables(tmp_path) -> None:
    """A legacy ``create_all`` database that already carries the tables still upgrades."""

    database_path = tmp_path / "ansich-evaluations-existing.db"
    config = _alembic_config(database_path)
    alembic_command.upgrade(config, PREVIOUS_REVISION)

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        AnsichEvaluationIndexRow.__table__.create(engine)
        AnsichReleaseQualityStatsRow.__table__.create(engine)
    finally:
        engine.dispose()

    alembic_command.upgrade(config, "head")

    table_names, columns, indexes, revision = _sqlite_schema(database_path)

    assert EVALUATION_TABLES <= table_names
    assert columns["ansich_evaluation_index"] == {column.name for column in AnsichEvaluationIndexRow.__table__.columns}
    assert indexes["ansich_evaluation_index"] == {index.name for index in AnsichEvaluationIndexRow.__table__.indexes}
    assert revision == EVALUATION_REVISION


def test_evaluation_migration_downgrade_drops_tables(tmp_path) -> None:
    database_path = tmp_path / "ansich-evaluations-downgrade.db"
    config = _alembic_config(database_path)
    alembic_command.upgrade(config, "head")

    alembic_command.downgrade(config, PREVIOUS_REVISION)

    table_names, _columns, _indexes, revision = _sqlite_schema(database_path)

    assert not (EVALUATION_TABLES & table_names)
    assert revision == PREVIOUS_REVISION


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _producer(name: str = "ansich-evaluation-intake") -> Producer:
    return Producer(name=name, version="1", instance_id="test")


@asynccontextmanager
async def _evaluation_service(
    tmp_path: Path,
    database_name: str,
    **overrides: object,
) -> AsyncIterator[tuple[AnsichService, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / database_name}",
        # The dependency-wait tests poll the job table while the projector loop
        # writes to it; without a busy timeout SQLite reports "database is
        # locked" instead of waiting for the writer.
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings: dict[str, object] = {
        "flush_interval_ms": 60_000,
        "terminal_flush_timeout_ms": 10_000,
        "projector_poll_interval_ms": 5,
        "operations_assessment_interval_ms": 60_000,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(session_factory, **settings)
    await service.start()
    try:
        yield service, session_factory
    finally:
        await service.stop()
        await engine.dispose()


def _task_created(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{run_id}:task:created",
    )


def _release(*, effective_model: str = "provider/model-v1"):
    return build_agent_release(
        AgentRuntimeDescriptor(
            namespace="deerflow",
            agent_name="lead-agent",
            requested_model="requested-alias",
            effective_model=effective_model,
            model_provider="provider",
            model_behavior_parameters={"model": effective_model},
            rendered_base_prompt="You are DeerFlow.",
            prompt_template_id="lead-v1",
            effective_policies={"non_interactive": False},
            runtime_build=RuntimeBuildDescriptor(package_version="2.1.0"),
        )
    )


def _release_resolved(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.agent_release_resolved(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_OCCURRED_AT,
        release=_release(),
        source_event_id=f"run:{run_id}:agent-release:resolved",
    )


def _step_started(task_id: str, step_id: str, *, step_seq: int = 1) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=_OCCURRED_AT,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=_producer("ansich-step-probe"),
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": step_seq, "actor_kind": "lead_agent"},
    )


def _record(task_id: str, **overrides: object) -> EvaluationRecord:
    fields: dict[str, object] = {
        "subject_type": "task",
        "subject_id": task_id,
        "task_id": task_id,
        "evaluation_kind": "benchmark_assertion",
        "dimension": "correctness",
        "verdict": "pass",
        "assessor": _ASSESSOR,
        "fidelity_class": "hard",
        "suite": "ansich-regression",
        "suite_version": "2026.08.1",
        "case_id": "case-1",
        "run_id": "bench-run-1",
        "occurred_at": _OCCURRED_AT,
    }
    fields.update(overrides)
    return EvaluationRecord(**fields)


def _annotation(task_id: str, **overrides: object) -> EvaluationRecord:
    fields: dict[str, object] = {
        "evaluation_kind": "developer_annotation",
        "fidelity_class": "soft",
        "suite": None,
        "suite_version": None,
        "case_id": None,
        "run_id": None,
    }
    fields.update(overrides)
    return _record(task_id, **fields)


async def _requeue_evaluation_jobs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(AnsichProjectionJobRow)
            .where(AnsichProjectionJobRow.projector_name == "evaluation-projector")
            .values(
                status="pending",
                attempts=0,
                available_at=datetime.now(UTC),
                dependency_pending_since=None,
                lease_owner=None,
                lease_expires_at=None,
                last_error=None,
            )
        )


async def _wait_for_dependency_pending_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    reason: str,
) -> AnsichProjectionJobRow | None:
    """Sample the evaluation job once it has parked on its dependency wait.

    The projector retries a dependency-pending job every 250ms, so a single
    read can land inside the brief ``processing`` window of a retry; poll until
    the job is back in its waiting state carrying the recorded reason.
    """

    job = None
    for _ in range(200):
        async with session_factory() as session:
            job = await session.scalar(
                select(AnsichProjectionJobRow).where(
                    AnsichProjectionJobRow.projector_name == "evaluation-projector",
                )
            )
        if job is not None and job.status == "pending" and reason in (job.last_error or ""):
            return job
        await anyio.sleep(0.05)
    return job


async def _evaluation_job_statuses(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, ...]:
    statuses: tuple[str, ...] = ()
    for _ in range(200):
        async with session_factory() as session:
            statuses = tuple(
                (
                    await session.execute(
                        select(AnsichProjectionJobRow.status).where(
                            AnsichProjectionJobRow.projector_name == "evaluation-projector",
                        )
                    )
                ).scalars()
            )
        if statuses and all(status in {"completed", "failed"} for status in statuses):
            return statuses
        await anyio.sleep(0.05)
    return statuses


async def _projection_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, tuple[tuple[object, ...], ...]]:
    async with session_factory() as session:
        index_rows = tuple(
            (
                row.evaluation_obs_id,
                row.subject_type,
                row.subject_id,
                row.task_id,
                row.evaluation_kind,
                row.dimension,
                row.verdict,
                row.score,
                row.scale_min,
                row.scale_max,
                row.scale_higher_is_better,
                row.assessor_name,
                row.assessor_version,
                row.authority_class,
                row.fidelity_class,
                row.cohort_key,
                row.suite_id,
                row.suite_version,
                row.case_id,
                _utc(row.occurred_at),
                row.projector_version,
            )
            for row in (await session.execute(select(AnsichEvaluationIndexRow).order_by(AnsichEvaluationIndexRow.evaluation_obs_id))).scalars()
        )
        stats_rows = tuple(
            (
                row.release_id,
                row.cohort_key,
                row.dimension,
                row.assessed_count,
                row.pass_count,
                row.fail_count,
                row.partial_count,
                row.score_sum,
                row.score_count,
                row.scale_min,
                row.scale_max,
                row.scale_higher_is_better,
                _utc(row.as_of),
                row.projector_version,
            )
            for row in (
                await session.execute(
                    select(AnsichReleaseQualityStatsRow).order_by(
                        AnsichReleaseQualityStatsRow.release_id,
                        AnsichReleaseQualityStatsRow.cohort_key,
                        AnsichReleaseQualityStatsRow.dimension,
                    )
                )
            ).scalars()
        )
        belief_rows = tuple(
            (
                current.subject_id,
                current.field_name,
                assertion.value_json,
                assertion.authority_class,
                assertion.fidelity_class,
                _utc(assertion.as_of),
                assertion.assessor_name,
                assertion.assessor_version,
                assertion.config_hash,
            )
            for current, assertion in (
                await session.execute(
                    select(AnsichCurrentBeliefRow, AnsichBeliefAssertionRow)
                    .join(
                        AnsichBeliefAssertionRow,
                        AnsichBeliefAssertionRow.assertion_id == AnsichCurrentBeliefRow.assertion_id,
                    )
                    .where(AnsichCurrentBeliefRow.field_name.like("quality.%"))
                    .order_by(
                        AnsichCurrentBeliefRow.subject_id,
                        AnsichCurrentBeliefRow.field_name,
                    )
                )
            ).all()
        )
    return {"index": index_rows, "stats": stats_rows, "beliefs": belief_rows}


@pytest.mark.anyio
async def test_evaluation_projects_an_index_row_and_a_quality_belief(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-happy-run"
    record = _record(
        task_id,
        verdict="fail",
        score=0.25,
        scale=_UNIT_SCALE,
        case_id="case-happy",
    )
    observation = build_evaluation_observation(record, producer=_producer())

    async with _evaluation_service(tmp_path, "ansich-evaluation-happy.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), observation))
        await service.flush_task(task_id)

        async with session_factory() as session:
            index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
            failure_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))
        belief = await service.get_current_belief(task_id, "quality.correctness")

    assert index_row is not None
    assert (index_row.subject_type, index_row.subject_id, index_row.task_id) == ("task", task_id, task_id)
    assert index_row.evaluation_kind == "benchmark_assertion"
    assert index_row.dimension == "correctness"
    assert index_row.verdict == "fail"
    assert index_row.score == 0.25
    assert (index_row.scale_min, index_row.scale_max, index_row.scale_higher_is_better) == (0.0, 1.0, True)
    assert (index_row.assessor_name, index_row.assessor_version) == (_ASSESSOR.name, _ASSESSOR.version)
    assert index_row.authority_class == "deterministic"
    assert index_row.fidelity_class == "hard"
    assert index_row.cohort_key == "ansich-regression@2026.08.1"
    assert (index_row.suite_id, index_row.suite_version, index_row.case_id) == (
        "ansich-regression",
        "2026.08.1",
        "case-happy",
    )
    assert _utc(index_row.occurred_at) == _OCCURRED_AT
    assert index_row.projector_version == "1"
    assert failure_count == 0

    assert belief is not None
    assert belief.field_name == "quality.correctness"
    assert belief.value == {
        "verdict": "fail",
        "score": 0.25,
        "scale": {"min": 0.0, "max": 1.0, "higher_is_better": True},
        "evaluation_kind": "benchmark_assertion",
        "cohort_key": "ansich-regression@2026.08.1",
        "suite": "ansich-regression",
    }
    assert belief.authority_class == "deterministic"
    assert belief.fidelity_class == "hard"
    assert belief.assessor == _ASSESSOR
    assert belief.evidence_obs_ids == (observation.obs_id,)
    assert _utc(belief.as_of) == _OCCURRED_AT


@pytest.mark.anyio
async def test_evaluation_authority_and_fidelity_come_from_the_payload_not_the_envelope(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-authority-run"
    records = {
        "correctness": _record(
            task_id,
            dimension="correctness",
            evaluation_kind="benchmark_assertion",
            fidelity_class="hard",
            case_id="case-hard",
        ),
        "completeness": _record(
            task_id,
            dimension="completeness",
            evaluation_kind="unit_test",
            fidelity_class="rule",
            case_id="case-rule",
        ),
        "relevance": _annotation(task_id, dimension="relevance", human_override=True),
        "safety": _annotation(
            task_id,
            dimension="safety",
            evaluation_kind="user_feedback",
            verdict="fail",
        ),
        "efficiency": _annotation(task_id, dimension="efficiency", evaluation_kind="llm_judge"),
    }
    observations = {dimension: build_evaluation_observation(record, producer=_producer(), source_event_id=f"evaluation:api:{dimension}") for dimension, record in records.items()}

    async with _evaluation_service(tmp_path, "ansich-evaluation-authority.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), *observations.values()))
        await service.flush_task(task_id)

        async with session_factory() as session:
            index_rows = {row.dimension: row for row in (await session.execute(select(AnsichEvaluationIndexRow))).scalars()}
            envelope_fidelity = tuple(
                (
                    await session.execute(
                        select(AnsichObservationRow.fidelity_class).where(
                            AnsichObservationRow.kind == "evaluation.recorded",
                        )
                    )
                ).scalars()
            )
        beliefs = {dimension: await service.get_current_belief(task_id, f"quality.{dimension}") for dimension in records}

    assert {dimension: row.authority_class for dimension, row in index_rows.items()} == {
        "correctness": "deterministic",
        "completeness": "configured_rule",
        "relevance": "human_override",
        "safety": "soft_human",
        "efficiency": "automated",
    }
    assert {dimension: row.fidelity_class for dimension, row in index_rows.items()} == {
        "correctness": "hard",
        "completeness": "rule",
        "relevance": "soft",
        "safety": "soft",
        "efficiency": "soft",
    }
    # The Observation column is a Literal["hard"]; a projector reading it would
    # misclassify every soft/rule evaluation.
    assert set(envelope_fidelity) == {"hard"}
    assert {dimension: belief.authority_class for dimension, belief in beliefs.items()} == {
        "correctness": "deterministic",
        "completeness": "configured_rule",
        "relevance": "human_override",
        "safety": "soft_human",
        "efficiency": "automated",
    }


@pytest.mark.anyio
async def test_externalized_evaluation_payload_is_hydrated_before_projection(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-external-run"
    record = _record(task_id, rationale="x" * 80_000, case_id="case-external")
    observation = build_evaluation_observation(record, producer=_producer())

    async with _evaluation_service(tmp_path, "ansich-evaluation-external.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), observation))
        await service.flush_task(task_id)

        async with session_factory() as session:
            stored = await session.scalar(
                select(AnsichObservationRow).where(
                    AnsichObservationRow.obs_id == observation.obs_id,
                )
            )
            index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
        belief = await service.get_current_belief(task_id, "quality.correctness")

    assert stored is not None
    assert stored.payload_json is None
    assert stored.payload_ref_id is not None
    assert index_row is not None
    assert index_row.case_id == "case-external"
    assert belief is not None


@pytest.mark.anyio
async def test_custom_dimension_records_an_index_row_without_an_assertion(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-custom-run"
    record = _annotation(task_id, dimension="custom", verdict="partial")
    observation = build_evaluation_observation(
        record,
        producer=_producer(),
        source_event_id="evaluation:api:custom",
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-custom.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), observation))
        await service.flush_task(task_id)

        async with session_factory() as session:
            index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
            quality_assertions = await session.scalar(
                select(func.count())
                .select_from(AnsichBeliefAssertionRow)
                .where(
                    AnsichBeliefAssertionRow.field_name.like("quality.%"),
                )
            )
            failure_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert index_row is not None
    assert index_row.dimension == "custom"
    assert quality_assertions == 0
    assert failure_count == 0


@pytest.mark.anyio
async def test_correctness_fail_produces_no_behavior_assertion(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-behavior-run"
    record = _record(task_id, verdict="fail", case_id="case-behavior")
    observation = build_evaluation_observation(record, producer=_producer())

    async with _evaluation_service(tmp_path, "ansich-evaluation-behavior.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), observation))
        await service.flush_task(task_id)

        async with session_factory() as session:
            field_names = set(
                (
                    await session.execute(
                        select(AnsichBeliefAssertionRow.field_name).where(
                            AnsichBeliefAssertionRow.subject_id == task_id,
                        )
                    )
                ).scalars()
            )

    assert "quality.correctness" in field_names
    assert not {name for name in field_names if name.startswith("behavior")}


@pytest.mark.anyio
async def test_earliest_erroneous_step_belief_carries_the_step_sequence(tmp_path) -> None:
    task_id, run_id, step_id = new_id(), "eval-step-run", new_id()
    record = _annotation(
        task_id,
        dimension="earliest_erroneous_step",
        verdict="fail",
        actual=step_id,
    )
    observation = build_evaluation_observation(
        record,
        producer=_producer(),
        source_event_id="evaluation:api:earliest-erroneous-step",
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-earliest.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _step_started(task_id, step_id, step_seq=4),
                observation,
            )
        )
        await service.flush_task(task_id)

        async with session_factory() as session:
            index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
        belief = await service.get_current_belief(task_id, "quality.earliest_erroneous_step")

    assert index_row is not None
    assert index_row.dimension == "earliest_erroneous_step"
    assert belief is not None
    assert belief.value == {"step_id": step_id, "step_seq": 4, "verdict": "fail"}
    assert belief.authority_class == "soft_human"


@pytest.mark.anyio
async def test_earliest_erroneous_step_waits_for_the_referenced_step(tmp_path) -> None:
    task_id, run_id, step_id = new_id(), "eval-step-wait-run", new_id()
    observation = build_evaluation_observation(
        _annotation(
            task_id,
            dimension="earliest_erroneous_step",
            verdict="fail",
            actual=step_id,
        ),
        producer=_producer(),
        source_event_id="evaluation:api:earliest-erroneous-step-wait",
    )

    async with _evaluation_service(
        tmp_path,
        "ansich-evaluation-earliest-wait.db",
        # flush_task is deliberately unused while the dependency is unmet: its
        # terminal timeout would cancel a claim mid-transaction. The background
        # writer and projector loops drive the wait instead.
        flush_interval_ms=20,
    ) as (service, session_factory):
        service.record_batch((_task_created(task_id, run_id), observation))
        waiting_job = await _wait_for_dependency_pending_job(
            session_factory,
            reason=f"waiting for Step {step_id}",
        )

        async with session_factory() as session:
            pending_errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

        assert waiting_job is not None
        assert waiting_job.status == "pending"
        assert waiting_job.attempts == 0
        assert waiting_job.dependency_pending_since is not None
        assert pending_errors == 0

        service.record(_step_started(task_id, step_id, step_seq=9))
        statuses = await _evaluation_job_statuses(session_factory)
        belief = await service.get_current_belief(task_id, "quality.earliest_erroneous_step")

        async with session_factory() as session:
            healed_errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert statuses == ("completed",)
    assert healed_errors == 0
    assert belief is not None
    assert belief.value == {"step_id": step_id, "step_seq": 9, "verdict": "fail"}


@pytest.mark.anyio
async def test_earliest_erroneous_step_from_another_task_fails_the_job(tmp_path) -> None:
    task_id, other_task_id = new_id(), new_id()
    step_id = new_id()
    record = _annotation(
        task_id,
        dimension="earliest_erroneous_step",
        verdict="fail",
        actual=step_id,
    )
    observation = build_evaluation_observation(
        record,
        producer=_producer(),
        source_event_id="evaluation:api:foreign-step",
    )

    async with _evaluation_service(
        tmp_path,
        "ansich-evaluation-foreign-step.db",
        projector_max_attempts=1,
    ) as (service, session_factory):
        service.record_batch(
            (
                _task_created(task_id, "eval-foreign-run"),
                _task_created(other_task_id, "eval-foreign-other-run"),
                _step_started(other_task_id, step_id, step_seq=2),
                observation,
            )
        )
        await service.flush_task(other_task_id)
        await service.flush_task(task_id)
        statuses = await _evaluation_job_statuses(session_factory)

        async with session_factory() as session:
            job = await session.scalar(
                select(AnsichProjectionJobRow).where(
                    AnsichProjectionJobRow.projector_name == "evaluation-projector",
                )
            )
            index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
            errors = tuple((await session.execute(select(AnsichProjectionErrorRow))).scalars())

    assert statuses == ("failed",)
    assert job is not None
    assert "earliest erroneous step must belong to the evaluated Task" in (job.last_error or "")
    assert index_row is None
    assert [error.error_type for error in errors] == ["ValueError"]


@pytest.mark.anyio
async def test_evaluation_waits_for_its_subject_step_then_self_heals(tmp_path) -> None:
    task_id, run_id, step_id = new_id(), "eval-pending-run", new_id()
    record = _annotation(
        task_id,
        subject_type="step",
        subject_id=step_id,
        dimension="correctness",
        verdict="fail",
    )
    observation = build_evaluation_observation(
        record,
        producer=_producer(),
        source_event_id="evaluation:api:step-subject",
    )

    async with _evaluation_service(
        tmp_path,
        "ansich-evaluation-pending.db",
        # flush_task is deliberately unused while the dependency is unmet: its
        # terminal timeout would cancel a claim mid-transaction. The background
        # writer and projector loops drive the wait instead.
        flush_interval_ms=20,
    ) as (service, session_factory):
        service.record_batch((_task_created(task_id, run_id), observation))
        waiting_job = await _wait_for_dependency_pending_job(
            session_factory,
            reason="waiting for subject Entity",
        )

        async with session_factory() as session:
            pending_index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
            pending_errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

        assert waiting_job is not None
        assert waiting_job.status == "pending"
        # A replay-safe dependency wait must not burn a projector attempt.
        assert waiting_job.attempts == 0
        assert waiting_job.dependency_pending_since is not None
        assert pending_index_row is None
        assert pending_errors == 0

        service.record(_step_started(task_id, step_id, step_seq=1))
        statuses = await _evaluation_job_statuses(session_factory)

        async with session_factory() as session:
            healed_index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
            healed_errors = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))
        belief = await service.get_current_belief(step_id, "quality.correctness")

    assert statuses == ("completed",)
    assert healed_index_row is not None
    assert healed_index_row.subject_type == "step"
    assert healed_index_row.subject_id == step_id
    assert healed_errors == 0
    assert belief is not None
    assert belief.subject_id == step_id


@pytest.mark.anyio
async def test_reprojecting_the_same_evaluation_is_idempotent(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-idempotent-run"
    record = _record(task_id, score=1.0, scale=_UNIT_SCALE, case_id="case-idempotent")
    observation = build_evaluation_observation(record, producer=_producer())

    async with _evaluation_service(tmp_path, "ansich-evaluation-idempotent.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _release_resolved(task_id, run_id),
                observation,
            )
        )
        await service.flush_task(task_id)
        first = await _projection_snapshot(session_factory)

        await _requeue_evaluation_jobs(session_factory)
        statuses = await _evaluation_job_statuses(session_factory)
        second = await _projection_snapshot(session_factory)

        async with session_factory() as session:
            index_count = await session.scalar(select(func.count()).select_from(AnsichEvaluationIndexRow))
            assertion_count = await session.scalar(
                select(func.count())
                .select_from(AnsichBeliefAssertionRow)
                .where(
                    AnsichBeliefAssertionRow.field_name == "quality.correctness",
                )
            )
            failure_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert statuses == ("completed",)
    assert index_count == 1
    assert assertion_count == 1
    assert failure_count == 0
    assert first == second


@pytest.mark.anyio
async def test_conflicting_index_reprojection_fails_the_job(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-conflict-run"
    record = _record(task_id, verdict="fail", case_id="case-conflict")
    observation = build_evaluation_observation(record, producer=_producer())

    async with _evaluation_service(
        tmp_path,
        "ansich-evaluation-index-conflict.db",
        projector_max_attempts=1,
    ) as (service, session_factory):
        service.record_batch((_task_created(task_id, run_id), observation))
        await service.flush_task(task_id)

        async with session_factory() as session, session.begin():
            await session.execute(update(AnsichEvaluationIndexRow).where(AnsichEvaluationIndexRow.evaluation_obs_id == observation.obs_id).values(verdict="pass"))
        await _requeue_evaluation_jobs(session_factory)
        statuses = await _evaluation_job_statuses(session_factory)

        async with session_factory() as session:
            job = await session.scalar(
                select(AnsichProjectionJobRow).where(
                    AnsichProjectionJobRow.projector_name == "evaluation-projector",
                )
            )
            errors = tuple((await session.execute(select(AnsichProjectionErrorRow))).scalars())

    assert statuses == ("failed",)
    assert job is not None
    assert "conflicts with an existing projection" in (job.last_error or "")
    assert [error.error_type for error in errors] == ["ValueError"]


@pytest.mark.anyio
async def test_conflicting_pass_and_fail_assertions_are_both_retained(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-conflict-belief-run"
    benchmark = build_evaluation_observation(
        _record(task_id, verdict="fail", case_id="case-benchmark"),
        producer=_producer(),
    )
    override = build_evaluation_observation(
        _annotation(task_id, verdict="pass", human_override=True),
        producer=_producer(),
        source_event_id="evaluation:api:human-override",
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-belief-conflict.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), benchmark, override))
        await service.flush_task(task_id)

        async with session_factory() as session:
            assertion_count = await session.scalar(
                select(func.count())
                .select_from(AnsichBeliefAssertionRow)
                .where(
                    AnsichBeliefAssertionRow.subject_id == task_id,
                    AnsichBeliefAssertionRow.field_name == "quality.correctness",
                )
            )
        belief = await service.get_current_belief(task_id, "quality.correctness")

    # The deterministic benchmark fail is retained alongside the human override
    # that outranks it; the resolver reports the loser as a conflict rather than
    # the projector overwriting it.
    assert assertion_count == 2
    conflicting_assertion_count = assertion_count - 1
    assert conflicting_assertion_count == 1
    assert belief is not None
    assert belief.authority_class == "human_override"
    assert belief.value["verdict"] == "pass"
    assert belief.evidence_obs_ids == (override.obs_id,)


@pytest.mark.anyio
async def test_release_quality_stats_aggregate_current_beliefs_for_a_cohort(tmp_path) -> None:
    first_task, second_task = new_id(), new_id()
    later = _OCCURRED_AT + timedelta(minutes=5)
    passing = build_evaluation_observation(
        _record(first_task, verdict="pass", score=1.0, scale=_UNIT_SCALE, case_id="case-a", run_id="bench-a"),
        producer=_producer(),
    )
    failing = build_evaluation_observation(
        _record(
            second_task,
            verdict="fail",
            score=0.0,
            scale=_UNIT_SCALE,
            case_id="case-b",
            run_id="bench-b",
            occurred_at=later,
        ),
        producer=_producer(),
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-release-stats.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(first_task, "eval-stats-run-a"),
                _release_resolved(first_task, "eval-stats-run-a"),
                passing,
            )
        )
        await service.flush_task(first_task)
        service.record_batch(
            (
                _task_created(second_task, "eval-stats-run-b"),
                _release_resolved(second_task, "eval-stats-run-b"),
                failing,
            )
        )
        await service.flush_task(second_task)

        async with session_factory() as session:
            stats = tuple((await session.execute(select(AnsichReleaseQualityStatsRow))).scalars())
            release_id = await session.scalar(select(AnsichTaskAgentReleaseRow.release_id).where(AnsichTaskAgentReleaseRow.task_id == first_task))

    assert len(stats) == 1
    cell = stats[0]
    assert cell.release_id == release_id
    assert cell.cohort_key == "ansich-regression@2026.08.1"
    assert cell.dimension == "correctness"
    assert (cell.assessed_count, cell.pass_count, cell.fail_count, cell.partial_count) == (2, 1, 1, 0)
    assert cell.score_sum == 1.0
    assert cell.score_count == 2
    assert (cell.scale_min, cell.scale_max, cell.scale_higher_is_better) == (0.0, 1.0, True)
    assert _utc(cell.as_of) == later
    assert cell.projector_version == "1"


@pytest.mark.anyio
async def test_release_quality_stats_refuse_to_average_mixed_scales(tmp_path) -> None:
    first_task, second_task = new_id(), new_id()
    first_obs_id = "00000000-0000-4000-8000-0000000000a1"
    second_obs_id = "00000000-0000-4000-8000-0000000000b2"
    unit_scaled = build_evaluation_observation(
        _record(first_task, verdict="pass", score=1.0, scale=_UNIT_SCALE, case_id="case-a", run_id="bench-a"),
        producer=_producer(),
        obs_id=first_obs_id,
    )
    ten_scaled = build_evaluation_observation(
        _record(
            second_task,
            verdict="pass",
            score=8.0,
            scale=ScoreScale(min=0.0, max=10.0, higher_is_better=True),
            case_id="case-b",
            run_id="bench-b",
        ),
        producer=_producer(),
        obs_id=second_obs_id,
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-mixed-scales.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(first_task, "eval-scale-run-a"),
                _release_resolved(first_task, "eval-scale-run-a"),
                unit_scaled,
            )
        )
        await service.flush_task(first_task)
        service.record_batch(
            (
                _task_created(second_task, "eval-scale-run-b"),
                _release_resolved(second_task, "eval-scale-run-b"),
                ten_scaled,
            )
        )
        await service.flush_task(second_task)

        async with session_factory() as session:
            stats = tuple((await session.execute(select(AnsichReleaseQualityStatsRow))).scalars())

    assert len(stats) == 1
    cell = stats[0]
    assert (cell.assessed_count, cell.pass_count, cell.fail_count) == (2, 2, 0)
    assert cell.score_sum is None
    assert cell.score_count == 0
    # Deterministic tiebreak: the lowest evaluation_obs_id contributes the scale.
    assert (cell.scale_min, cell.scale_max, cell.scale_higher_is_better) == (0.0, 1.0, True)


@pytest.mark.anyio
async def test_release_quality_stats_use_the_empty_cohort_sentinel(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-no-cohort-run"
    observation = build_evaluation_observation(
        _annotation(task_id, evaluation_kind="user_feedback", verdict="partial"),
        producer=_producer(),
        source_event_id="evaluation:api:no-cohort",
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-no-cohort.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(task_id, run_id),
                _release_resolved(task_id, run_id),
                observation,
            )
        )
        await service.flush_task(task_id)

        async with session_factory() as session:
            stats = tuple((await session.execute(select(AnsichReleaseQualityStatsRow))).scalars())
            index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)

    assert index_row is not None
    assert index_row.cohort_key is None
    assert len(stats) == 1
    cell = stats[0]
    assert cell.cohort_key == ""
    assert (cell.assessed_count, cell.pass_count, cell.fail_count, cell.partial_count) == (1, 0, 0, 1)
    assert cell.score_sum is None
    assert cell.score_count == 0
    assert (cell.scale_min, cell.scale_max, cell.scale_higher_is_better) == (None, None, None)


@pytest.mark.anyio
async def test_task_without_a_release_binding_skips_release_stats(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-unbound-run"
    observation = build_evaluation_observation(
        _record(task_id, case_id="case-unbound"),
        producer=_producer(),
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-unbound.db") as (
        service,
        session_factory,
    ):
        service.record_batch((_task_created(task_id, run_id), observation))
        await service.flush_task(task_id)

        async with session_factory() as session:
            stats_count = await session.scalar(select(func.count()).select_from(AnsichReleaseQualityStatsRow))
            index_row = await session.get(AnsichEvaluationIndexRow, observation.obs_id)
            failure_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))
        belief = await service.get_current_belief(task_id, "quality.correctness")

    assert stats_count == 0
    assert index_row is not None
    assert belief is not None
    assert failure_count == 0


@pytest.mark.anyio
async def test_rebuild_reproduces_index_rows_stats_and_current_beliefs(tmp_path) -> None:
    first_task, second_task = new_id(), new_id()
    step_id = new_id()
    later = _OCCURRED_AT + timedelta(minutes=3)
    benchmark = build_evaluation_observation(
        _record(first_task, verdict="fail", score=0.0, scale=_UNIT_SCALE, case_id="case-a", run_id="bench-a"),
        producer=_producer(),
    )
    override = build_evaluation_observation(
        _annotation(
            first_task,
            verdict="pass",
            human_override=True,
            occurred_at=later,
            cohort_key="ansich-regression@2026.08.1",
        ),
        producer=_producer(),
        source_event_id="evaluation:api:replay-override",
    )
    earliest = build_evaluation_observation(
        _annotation(
            first_task,
            dimension="earliest_erroneous_step",
            verdict="fail",
            actual=step_id,
        ),
        producer=_producer(),
        source_event_id="evaluation:api:replay-earliest",
    )
    second = build_evaluation_observation(
        _record(second_task, verdict="pass", score=1.0, scale=_UNIT_SCALE, case_id="case-b", run_id="bench-b"),
        producer=_producer(),
    )

    async with _evaluation_service(tmp_path, "ansich-evaluation-replay.db") as (
        service,
        session_factory,
    ):
        service.record_batch(
            (
                _task_created(first_task, "eval-replay-run-a"),
                _release_resolved(first_task, "eval-replay-run-a"),
                _step_started(first_task, step_id, step_seq=7),
                benchmark,
                override,
                earliest,
            )
        )
        await service.flush_task(first_task)
        service.record_batch(
            (
                _task_created(second_task, "eval-replay-run-b"),
                _release_resolved(second_task, "eval-replay-run-b"),
                second,
            )
        )
        await service.flush_task(second_task)
        before = await _projection_snapshot(session_factory)

        replayed = await service.rebuild_projections()
        after = await _projection_snapshot(session_factory)

        async with session_factory() as session:
            failure_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))

    assert replayed > 0
    assert failure_count == 0
    assert len(before["index"]) == 4
    assert len(before["beliefs"]) == 3
    assert len(before["stats"]) == 1
    # assessed/pass/fail/partial/score_sum/score_count: the human override wins
    # the first Task's belief and carries no score, so only one score is summed.
    assert before["stats"][0][3:9] == (2, 2, 0, 0, 1.0, 1)
    assert before["stats"][0][9:12] == (0.0, 1.0, True)
    assert _utc(before["stats"][0][12]) == later
    assert before == after
