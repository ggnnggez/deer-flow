"""Round-trip coverage for the Ansich environment-observability read-model tables.

Task 7 introduces three new tables (`ansich_environment_coverage`,
`ansich_environment_state`, `ansich_tool_env_samples`) plus one additive nullable
column (`ansich_alert_read_model.possibly_affected_task_ids`). This is a pure
model/schema test: it builds an in-memory SQLite database from `Base.metadata`,
inserts one row per new table, reads it back, and asserts the new AlertReadModel
column accepts a `None` write.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from deerflow.ansich.persistence.models import (
    AnsichAlertReadModelRow,
    AnsichEntityRow,
    AnsichEnvironmentCoverageRow,
    AnsichEnvironmentStateRow,
    AnsichObservationRow,
    AnsichToolEnvSampleRow,
)
from deerflow.persistence.base import Base

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed_observation_and_entity(session: Session, *, obs_id: str, entity_id: str) -> None:
    session.add(
        AnsichObservationRow(
            obs_id=obs_id,
            schema_version=1,
            kind="scope.created",
            occurred_at=NOW,
            recorded_at=NOW,
            task_id="task-seed",
            subject_type="scope",
            subject_id=entity_id,
            fidelity_class="hard",
            producer_name="test-environment-models",
            producer_version="1",
            producer_instance_id="test-instance",
            producer_seq=1,
            source_event_id=f"source:{obs_id}",
            correlation_id=f"corr:{obs_id}",
            payload_json={},
        )
    )
    session.flush()
    session.add(
        AnsichEntityRow(
            entity_id=entity_id,
            entity_type="scope",
            discovered_obs_id=obs_id,
        )
    )
    session.flush()


def test_environment_coverage_row_round_trips() -> None:
    engine = _engine()
    with Session(engine) as session:
        _seed_observation_and_entity(session, obs_id="obs-coverage-1", entity_id="scope-1")
        session.add(
            AnsichEnvironmentCoverageRow(
                scope_id="scope-1",
                environment_scope="io",
                coverage="full",
                provider="cgroup_v2",
                as_of=NOW,
                last_obs_id="obs-coverage-1",
                updated_at=NOW,
            )
        )
        session.commit()

        row = session.execute(select(AnsichEnvironmentCoverageRow)).scalar_one()
        assert row.scope_id == "scope-1"
        assert row.environment_scope == "io"
        assert row.coverage == "full"
        assert row.provider == "cgroup_v2"
        assert row.last_obs_id == "obs-coverage-1"


def test_environment_state_row_round_trips() -> None:
    engine = _engine()
    with Session(engine) as session:
        _seed_observation_and_entity(session, obs_id="obs-state-1", entity_id="scope-2")
        session.add(
            AnsichEnvironmentStateRow(
                scope_id="scope-2",
                environment_scope="io",
                metric="fd_count",
                latest_value=42,
                limit_value=1024,
                as_of=NOW,
                window_started_at=NOW,
                window_min_value=10,
                sample_count=5,
                consecutive_growth_count=3,
                growth_started_at=NOW,
                last_obs_id="obs-state-1",
                provider="cgroup_v2",
                updated_at=NOW,
            )
        )
        session.commit()

        row = session.execute(select(AnsichEnvironmentStateRow)).scalar_one()
        assert row.scope_id == "scope-2"
        assert row.metric == "fd_count"
        assert row.latest_value == 42
        assert row.limit_value == 1024
        assert row.window_min_value == 10
        assert row.sample_count == 5
        assert row.consecutive_growth_count == 3
        # SQLite drops tzinfo on round-trip; compare naive wall-clock values.
        assert row.growth_started_at == NOW.replace(tzinfo=None)
        assert row.provider == "cgroup_v2"


def test_environment_state_row_allows_no_configured_limit_and_no_growth_window() -> None:
    engine = _engine()
    with Session(engine) as session:
        _seed_observation_and_entity(session, obs_id="obs-state-2", entity_id="scope-3")
        session.add(
            AnsichEnvironmentStateRow(
                scope_id="scope-3",
                environment_scope="memory",
                metric="rss_bytes",
                latest_value=1000,
                limit_value=None,
                as_of=NOW,
                window_started_at=NOW,
                window_min_value=1000,
                sample_count=1,
                consecutive_growth_count=0,
                growth_started_at=None,
                last_obs_id="obs-state-2",
                provider="proc_fs",
                updated_at=NOW,
            )
        )
        session.commit()

        row = session.execute(select(AnsichEnvironmentStateRow)).scalar_one()
        assert row.limit_value is None
        assert row.growth_started_at is None


def test_tool_env_sample_row_round_trips_without_fk_dependencies() -> None:
    engine = _engine()
    with Session(engine) as session:
        # Deliberately does NOT seed AnsichTaskRow/AnsichScopeRow/AnsichObservationRow
        # parents: per Task 7's brief, this table carries no foreign keys, so a
        # per-command sample can be written before its Task/Scope/ToolCall
        # projections land (Task 8 dependency-wait exemption).
        session.add(
            AnsichToolEnvSampleRow(
                tool_call_id="tool-call-1",
                task_id="task-1",
                scope_id="scope-1",
                io_read_bytes=2048,
                io_write_bytes=512,
                fd_peak=7,
                sample_count=3,
                started_at=NOW,
                ended_at=NOW,
                obs_id="obs-tool-1",
            )
        )
        session.commit()

        row = session.execute(select(AnsichToolEnvSampleRow)).scalar_one()
        assert row.tool_call_id == "tool-call-1"
        assert row.task_id == "task-1"
        assert row.scope_id == "scope-1"
        assert row.io_read_bytes == 2048
        assert row.io_write_bytes == 512
        assert row.fd_peak == 7
        assert row.sample_count == 3
        assert row.obs_id == "obs-tool-1"


def test_tool_env_sample_row_allows_null_io_counters() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(
            AnsichToolEnvSampleRow(
                tool_call_id="tool-call-2",
                task_id="task-1",
                scope_id="scope-1",
                io_read_bytes=None,
                io_write_bytes=None,
                fd_peak=None,
                sample_count=1,
                started_at=NOW,
                ended_at=NOW,
                obs_id="obs-tool-2",
            )
        )
        session.commit()

        row = session.execute(select(AnsichToolEnvSampleRow)).scalar_one()
        assert row.io_read_bytes is None
        assert row.io_write_bytes is None
        assert row.fd_peak is None


def test_alert_read_model_possibly_affected_task_ids_accepts_null_write() -> None:
    # This is a pure schema/round-trip test: the read-model row's `alert_id`
    # FK is not exercised here (SQLite does not enforce FKs unless
    # `PRAGMA foreign_keys=ON` is set, and the full Alert/BeliefAssertion
    # parent chain is orthogonal to what Task 7 adds). Service-level FK
    # behavior for `ansich_alerts` is covered by the existing alert suite.
    engine = _engine()
    with Session(engine) as session:
        session.add(
            AnsichAlertReadModelRow(
                alert_id="alert-1",
                subject_id="alert-1",
                alert_type="budget_warning",
                severity="warning",
                workflow_state="open",
                shadow=False,
                opened_at=NOW,
                as_of=NOW,
                updated_at=NOW,
                summary_json={},
                evidence_count=0,
                possibly_affected_task_ids=None,
            )
        )
        session.commit()

        row = session.execute(select(AnsichAlertReadModelRow)).scalar_one()
        assert row.possibly_affected_task_ids is None


def test_alert_read_model_possibly_affected_task_ids_round_trips_list() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(
            AnsichAlertReadModelRow(
                alert_id="alert-2",
                subject_id="alert-2",
                alert_type="budget_warning",
                severity="warning",
                workflow_state="open",
                shadow=False,
                opened_at=NOW,
                as_of=NOW,
                updated_at=NOW,
                summary_json={},
                evidence_count=0,
                possibly_affected_task_ids=["task-a", "task-b"],
            )
        )
        session.commit()

        row = session.execute(select(AnsichAlertReadModelRow)).scalar_one()
        assert row.possibly_affected_task_ids == ["task-a", "task-b"]
