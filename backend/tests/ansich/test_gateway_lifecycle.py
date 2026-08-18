from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

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
