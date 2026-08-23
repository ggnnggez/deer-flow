import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from ansich.contracts import ShutdownReport, ShutdownStep
from fastapi import FastAPI

import deerflow.ansich as ansich_module
import deerflow.runtime as runtime_module
from app.gateway import deps as gateway_deps
from deerflow.config.ansich_config import AnsichConfig
from deerflow.persistence import engine as engine_module
from deerflow.persistence import thread_meta as thread_meta_module
from deerflow.runtime.checkpointer import async_provider as checkpointer_module
from deerflow.runtime.events import store as event_store_module


@asynccontextmanager
async def value_context(value):
    yield value


class EmptyRunManager:
    def __init__(self, *, store, run_ownership_config=None) -> None:
        self.store = store

    async def reconcile_orphaned_inflight_runs(self, **kwargs):
        return []

    async def start_heartbeat(self) -> None:
        return None

    async def shutdown(self, *, timeout: float) -> None:
        return None


class EmptyBridge:
    pass


@pytest.mark.anyio
async def test_gateway_runtime_starts_and_stops_enabled_ansich_without_sql(monkeypatch):
    app = FastAPI()
    config = SimpleNamespace(
        ansich=AnsichConfig(
            enabled=True,
            evaluation_min_cohort_samples=7,
            evaluation_max_payload_bytes=4_096,
        ),
        database=SimpleNamespace(backend="memory", checkpoint_channel_mode="full"),
        run_events=SimpleNamespace(backend="memory"),
        stream_bridge=SimpleNamespace(recovered_stream_cleanup_delay_seconds=60.0),
        run_ownership=SimpleNamespace(heartbeat_enabled=False),
    )

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(engine_module, "init_engine_from_config", no_op)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    monkeypatch.setattr(engine_module, "close_engine", no_op)
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: value_context(EmptyBridge()))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: value_context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: value_context(object()))
    monkeypatch.setattr(thread_meta_module, "make_thread_store", lambda _sf, _store: object())
    monkeypatch.setattr(event_store_module, "make_run_event_store", lambda _config: object())
    monkeypatch.setattr(gateway_deps, "RunManager", EmptyRunManager)

    async with gateway_deps.langgraph_runtime(app, config):
        service = app.state.ansich_service
        assert service is not None
        assert service.get_health().status == "failed"
        # The evaluation knobs are frozen beside the service: ``ansich`` is a
        # restart-required section, so the routes must never read them live.
        assert app.state.ansich_evaluation_settings == gateway_deps.AnsichEvaluationSettings(
            min_cohort_samples=7,
            max_payload_bytes=4_096,
        )

    assert service.get_health().status == "stopped"


class OrphanedRunManager(EmptyRunManager):
    """A RunManager whose startup reconciliation found one orphaned Run."""

    async def reconcile_orphaned_inflight_runs(self, **kwargs):
        return [SimpleNamespace(run_id="run-orphaned-at-startup", thread_id="thread-orphaned")]


class SpyAnsichService:
    """Stands in for the collector so the lifespan's own two obligations are visible.

    Both of them are contracts between the Gateway and the collector rather
    than behaviour inside either: the lifespan must hand the RunManager's
    orphaned Runs to the collector *after* it has started (D8-3), and it must
    consume the shutdown report rather than dropping it — the report is the
    only account of a shutdown anybody gets.
    """

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.orphaned_runs: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def record_orphaned_run_evidence(self, run_ids, **kwargs) -> int:
        assert self.started, "the collector must be up before the correlation is handed to it"
        self.orphaned_runs.extend(run_ids)
        return len(self.orphaned_runs)

    async def stop(self):
        self.stopped = True
        return ShutdownReport(
            steps=(
                ShutdownStep(name="drain_writer", ok=True, timed_out=False, duration_ms=3, detail=None),
                ShutdownStep(name="drain_unreported_loss", ok=False, timed_out=True, duration_ms=2_500, detail="unreported_global_lost_ranges=2"),
            ),
            total_ms=2_503,
            budget_ms=5_000,
            completed=False,
        )


@pytest.mark.anyio
async def test_gateway_lifespan_correlates_orphaned_runs_and_logs_the_shutdown_report(monkeypatch, caplog):
    app = FastAPI()
    config = SimpleNamespace(
        ansich=AnsichConfig(enabled=True),
        database=SimpleNamespace(backend="memory", checkpoint_channel_mode="full"),
        run_events=SimpleNamespace(backend="memory"),
        stream_bridge=SimpleNamespace(recovered_stream_cleanup_delay_seconds=60.0),
        run_ownership=SimpleNamespace(heartbeat_enabled=False),
    )

    async def no_op(*args, **kwargs):
        return None

    spy = SpyAnsichService()
    monkeypatch.setattr(engine_module, "init_engine_from_config", no_op)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    monkeypatch.setattr(engine_module, "close_engine", no_op)
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: value_context(EmptyBridge()))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: value_context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: value_context(object()))
    monkeypatch.setattr(thread_meta_module, "make_thread_store", lambda _sf, _store: object())
    monkeypatch.setattr(event_store_module, "make_run_event_store", lambda _config: object())
    monkeypatch.setattr(gateway_deps, "RunManager", OrphanedRunManager)
    monkeypatch.setattr(ansich_module, "create_embedded_ansich_service", lambda _config, _sf: spy)

    with caplog.at_level(logging.INFO, logger="app.gateway.deps"):
        async with gateway_deps.langgraph_runtime(app, config):
            assert app.state.ansich_service is spy
            assert spy.orphaned_runs == ["run-orphaned-at-startup"]

    assert spy.stopped is True
    steps = [record for record in caplog.records if getattr(record, "event", None) == "ansich.shutdown.step"]
    assert [record.shutdown_step for record in steps] == ["drain_writer", "drain_unreported_loss"]
    # The step that left work behind is the one an operator greps for.
    assert steps[0].levelno == logging.INFO
    assert steps[1].levelno == logging.WARNING
    assert steps[1].shutdown_step_detail == "unreported_global_lost_ranges=2"
    (summary,) = [record for record in caplog.records if getattr(record, "event", None) == "ansich.shutdown.completed"]
    assert summary.shutdown_completed is False
    assert summary.shutdown_budget_ms == 5_000
