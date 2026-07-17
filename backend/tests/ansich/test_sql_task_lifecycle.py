import hashlib
from datetime import UTC, datetime

import pytest
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.execution import ANSICH_EXECUTION_CONTEXT_KEY, AnsichExecutionContext
from deerflow.ansich.middleware import AnsichAttemptMiddleware, AnsichDecisionMiddleware
from deerflow.ansich.persistence.models import (
    AnsichObservationRow,
    AnsichPayloadRow,
    AnsichProjectionErrorRow,
    AnsichProjectionJobRow,
    AnsichRelationRow,
    AnsichScopeRow,
)
from deerflow.ansich.persistence.sql import SqlAnsichBackend
from deerflow.persistence.base import Base


class _ObservedFinalModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "ansich-sql-observed"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="done",
                        usage_metadata={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
                        response_metadata={"finish_reason": "stop", "model_name": "observed-model"},
                    )
                )
            ]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.anyio
async def test_task_remains_queryable_after_service_restart(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 9, 0, tzinfo=UTC)
    first_service = create_sql_ansich_service(session_factory)
    await first_service.start()
    first_service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-persisted",
            occurred_at=observed_at,
            source_event_id="run:run-persisted:task:created",
            thread_id="thread-persisted",
            owner_id="owner-persisted",
        )
    )
    terminal = first_service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.completed",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-persisted",
            occurred_at=observed_at,
            source_event_id="run:run-persisted:task:completed",
        )
    )
    await first_service.flush_task(task_id)
    await first_service.stop()

    restarted_service = create_sql_ansich_service(session_factory)
    await restarted_service.start()
    try:
        task = await restarted_service.get_task(task_id)
    finally:
        await restarted_service.stop()
        await engine.dispose()

    assert task is not None
    assert task.source_id == "run-persisted"
    assert task.control.value == "completed"
    assert task.control.evidence_obs_ids == (terminal.obs_id,)


@pytest.mark.anyio
async def test_writer_deduplicates_observation_and_projects_owner_and_thread_scopes(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-scopes.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    observation = ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id="run-scoped",
        occurred_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        source_event_id="run:run-scoped:task:created",
        producer_seq=42,
        thread_id="thread-scoped",
        owner_id="owner-scoped",
    )

    try:
        service.record(observation)
        service.record(observation)
        await service.flush_task(task_id)
        async with session_factory() as session:
            observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow))
            job_count = await session.scalar(select(func.count()).select_from(AnsichProjectionJobRow))
            scope_count = await session.scalar(select(func.count()).select_from(AnsichScopeRow))
            relation_count = await session.scalar(select(func.count()).select_from(AnsichRelationRow))
            stored = await session.scalar(select(AnsichObservationRow))
    finally:
        await service.stop()
        await engine.dispose()

    assert observation_count == 1
    assert job_count == 2
    assert scope_count == 2
    assert relation_count == 2
    assert stored is not None
    assert stored.producer_seq == 42


@pytest.mark.anyio
async def test_projection_failure_keeps_raw_observation_and_records_retry_evidence(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-projector-failure.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory, projector_max_attempts=1)

    async def fail_control_projection(*_args, **_kwargs) -> None:
        raise RuntimeError("projector exploded")

    monkeypatch.setattr(backend, "_project_control", fail_control_projection)
    service = AnsichService(backend, flush_interval_ms=60_000)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-projector-failure",
            occurred_at=datetime(2026, 7, 17, 11, 0, tzinfo=UTC),
            source_event_id="run:run-projector-failure:task:created",
        )
    )

    try:
        flush = await service.flush_task(task_id)
        task = await service.get_task(task_id)
        health = service.get_health()
        async with session_factory() as session:
            observation_count = await session.scalar(select(func.count()).select_from(AnsichObservationRow))
            error_count = await session.scalar(select(func.count()).select_from(AnsichProjectionErrorRow))
            statuses = list((await session.execute(select(AnsichProjectionJobRow.status))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert flush.persisted is True
    assert observation_count == 1
    assert error_count == 1
    assert sorted(statuses) == ["completed", "failed"]
    assert task is not None
    assert task.control.value == "unknown"
    assert task.control.evidence_obs_ids == ()
    assert health.status == "degraded"
    assert health.failed_jobs == 1


@pytest.mark.anyio
async def test_projection_tables_can_be_rebuilt_from_durable_observations(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-replay.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)
    service = AnsichService(backend)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)

    try:
        for producer_seq, kind in enumerate(("task.created", "task.started", "task.completed"), start=1):
            service.record(
                ObservationEnvelope.task_lifecycle(
                    kind=kind,
                    task_id=task_id,
                    source_kind="deerflow_run",
                    source_id="run-replay",
                    occurred_at=observed_at,
                    source_event_id=f"run:run-replay:{kind}",
                    producer_seq=producer_seq,
                    thread_id="thread-replay",
                    owner_id="owner-replay",
                )
            )
        await service.flush_task(task_id)
        before = await service.get_task(task_id)

        # Rebuild must go through the service so it cannot race the
        # background projector loop over the same reset jobs (F7).
        assert await service.rebuild_projections() > 0

        after = await service.get_task(task_id)
        observations = await service.list_observations(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert before is not None
    assert after == before
    assert len(observations) == 3


@pytest.mark.anyio
async def test_projection_claim_order_follows_registry_priority_not_alphabetical(tmp_path, monkeypatch):
    """Adding a projector whose name sorts first alphabetically must not jump the queue (F4)."""
    from deerflow.ansich.persistence import sql as sql_module

    # Simulate a projector that consumes task.created: "usage-rollup" sorts
    # after "task-structural" in the old projector_name.desc() ordering, so an
    # alphabetical claim would run it before both existing projectors.
    monkeypatch.setattr(sql_module, "_PROJECTORS", (*sql_module._PROJECTORS, ("usage-rollup", "1")))
    monkeypatch.setattr(
        sql_module,
        "_PROJECTOR_KINDS",
        {**sql_module._PROJECTOR_KINDS, "usage-rollup": frozenset({"task.created"})},
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-priority.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)

    try:
        await backend.persist_and_project(
            [
                ObservationEnvelope.task_lifecycle(
                    kind="task.created",
                    task_id=new_id(),
                    source_kind="deerflow_run",
                    source_id="run-priority",
                    occurred_at=datetime(2026, 7, 17, 13, 0, tzinfo=UTC),
                    source_event_id="run:run-priority:task:created",
                )
            ]
        )
        claimed_names = []
        for _ in range(3):
            claim = await backend._claim_projection_job()
            assert claim is not None
            claimed_names.append(claim[1])
    finally:
        await engine.dispose()

    assert claimed_names == ["task-structural", "task-control", "usage-rollup"]


@pytest.mark.anyio
async def test_step_attempt_and_context_are_queryable_after_projection(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-step.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-step",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-step:task:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ObservedFinalModel(),
        tools=[],
        middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
    )

    try:
        await agent.ainvoke(
            {"messages": [HumanMessage(id="human-step", content="hello")]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        steps = await service.list_steps(task_id)
        context = await service.get_step_context(steps[0].step_id)
        assert await service.rebuild_projections() > 0
        rebuilt_steps = await service.list_steps(task_id)
        rebuilt_context = await service.get_step_context(steps[0].step_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert len(steps) == 1
    assert steps[0].step_seq == 1
    assert steps[0].result == "final_answer"
    assert steps[0].effective_attempt_no == 1
    assert len(steps[0].attempts) == 1
    assert steps[0].attempts[0].status == "success"
    assert steps[0].attempts[0].effective is True
    assert steps[0].attempts[0].usage == {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
    assert steps[0].attempts[0].response_metadata == {
        "finish_reason": "stop",
        "model_name": "observed-model",
    }
    assert context is not None
    assert [(item.ordinal, item.role, item.kind) for item in context.items] == [(0, "user", "user_input")]
    assert context.items[0].payload_available is True
    assert context.items[0].body is None
    assert rebuilt_steps == steps
    assert rebuilt_context == context


@pytest.mark.anyio
async def test_large_content_payload_is_externalized_but_remains_lazy_queryable(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-large-payload.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory, inline_payload_max_bytes=128)
    await service.start()
    task_id = new_id()
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-large-payload",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-large-payload:task:created",
        )
    )
    await service.flush_task(task_id)
    execution = AnsichExecutionContext(task_id=task_id, service=service)
    agent = create_agent(
        model=_ObservedFinalModel(),
        tools=[],
        middleware=[AnsichDecisionMiddleware(), AnsichAttemptMiddleware()],
    )
    visible_body = "x" * 500

    try:
        await agent.ainvoke(
            {"messages": [HumanMessage(id="human-large", content=visible_body)]},
            context={ANSICH_EXECUTION_CONTEXT_KEY: execution},
        )
        await service.flush_task(task_id)
        step = (await service.list_steps(task_id))[0]
        context = await service.get_step_context(step.step_id)
        assert context is not None
        raw = await service.get_content_block_payload(context.items[0].block_id)
        async with session_factory() as session:
            content_observation = await session.scalar(select(AnsichObservationRow).where(AnsichObservationRow.kind == "content.produced"))
            payload = await session.get(AnsichPayloadRow, content_observation.payload_ref_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert content_observation is not None
    assert content_observation.payload_json is None
    assert content_observation.payload_ref_id is not None
    assert payload is not None
    assert payload.byte_size > 128
    assert raw is not None
    assert raw.body == visible_body


@pytest.mark.anyio
async def test_equal_content_from_distinct_occurrences_shares_one_blob(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-content-blob.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    first_block_id = new_id()
    second_block_id = new_id()
    body = "same visible value"
    producer = Producer(name="blob-test", version="1", instance_id="test")
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-content-blob",
            occurred_at=datetime.now(UTC),
            source_event_id="run:run-content-blob:created",
        )
    )
    await service.flush_task(task_id)
    for ordinal, block_id in enumerate((first_block_id, second_block_id), start=1):
        service.record(
            ObservationEnvelope(
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                subject_type="content_block",
                subject_id=block_id,
                producer=producer,
                producer_seq=ordinal,
                source_event_id=f"blob:content:{ordinal}",
                correlation_id=task_id,
                payload={
                    "attempt_id": new_id(),
                    "occurrence_ordinal": ordinal,
                    "kind": "user_input",
                    "content_hash": hashlib.sha256(body.encode()).hexdigest(),
                    "body": body,
                    "visible_bytes": len(body.encode()),
                    "estimated_tokens": 5,
                    "sensitivity_flags": [],
                },
            )
        )

    try:
        await service.flush_task(task_id)
        first_payload = await service.get_content_block_payload(first_block_id)
        second_payload = await service.get_content_block_payload(second_block_id)
        async with session_factory() as session:
            blob_count = await session.scalar(text("SELECT count(*) FROM ansich_content_blobs"))
            block_count = await session.scalar(text("SELECT count(*) FROM ansich_content_blocks"))
            stored_payloads = list((await session.execute(select(AnsichObservationRow.payload_json).where(AnsichObservationRow.kind == "content.produced"))).scalars())
    finally:
        await service.stop()
        await engine.dispose()

    assert blob_count == 1
    assert block_count == 2
    assert first_payload is not None and first_payload.body == body
    assert second_payload is not None and second_payload.body == body
    assert all(payload is not None and "body" not in payload for payload in stored_payloads)


async def _record_incomplete_context(service: AnsichService, *, source_suffix: str) -> tuple[str, str, str, Producer]:
    task_id = new_id()
    step_id = new_id()
    attempt_id = new_id()
    snapshot_id = new_id()
    missing_block_id = new_id()
    producer = Producer(name="incomplete-test", version="1", instance_id=source_suffix)
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id=f"run-incomplete-context-{source_suffix}",
            occurred_at=observed_at,
            source_event_id=f"run:run-incomplete-context-{source_suffix}:created",
        )
    )
    await service.flush_task(task_id)
    started = ObservationEnvelope(
        kind="step.started",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=producer,
        producer_seq=1,
        source_event_id=f"incomplete:{source_suffix}:step:started",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
    )
    requested = ObservationEnvelope(
        kind="llm.requested",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=producer,
        producer_seq=2,
        source_event_id=f"incomplete:{source_suffix}:llm:requested",
        correlation_id=task_id,
        causation_obs_id=started.obs_id,
        payload={
            "attempt_no": 1,
            "snapshot_id": snapshot_id,
            "actor_kind": "lead_agent",
            "adapter_name": "test.Adapter",
            "adapter_version": "1",
            "configured_model": "test-model",
        },
    )
    snapshotted = ObservationEnvelope(
        kind="context.snapshotted",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="context_snapshot",
        subject_id=snapshot_id,
        producer=producer,
        producer_seq=3,
        source_event_id=f"incomplete:{source_suffix}:context:snapshotted",
        correlation_id=task_id,
        causation_obs_id=requested.obs_id,
        payload={
            "attempt_id": attempt_id,
            "attempt_no": 1,
            "message_count": 1,
            "tool_schema_count": 0,
            "visible_bytes": 7,
            "estimated_tokens": 2,
            "estimator_name": "chars",
            "estimator_version": "1",
            "adapter_name": "test.Adapter",
            "adapter_version": "1",
            "configured_model": "test-model",
            "generation_settings": {},
            "redactions": [],
            "warnings": [],
            "items": [
                {
                    "ordinal": 0,
                    "channel": "message",
                    "role": "user",
                    "message_id": "missing-message",
                    "name": None,
                    "block_id": missing_block_id,
                    "visible_bytes": 7,
                    "estimated_tokens": 2,
                    "metadata": {"message_ordinal": 0, "part_ordinal": 0},
                }
            ],
        },
    )
    responded = ObservationEnvelope(
        kind="llm.responded",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="llm_attempt",
        subject_id=attempt_id,
        producer=producer,
        producer_seq=4,
        source_event_id=f"incomplete:{source_suffix}:llm:responded",
        correlation_id=task_id,
        causation_obs_id=requested.obs_id,
        payload={"attempt_no": 1, "latency_ms": 1, "usage": {}, "response_metadata": {}},
    )
    closed = ObservationEnvelope(
        kind="step.closed",
        occurred_at=observed_at,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=producer,
        producer_seq=5,
        source_event_id=f"incomplete:{source_suffix}:step:closed",
        correlation_id=task_id,
        causation_obs_id=responded.obs_id,
        payload={"result": "final_answer", "effective_attempt_no": 1, "issued_tools": []},
    )

    for observation in (started, requested, snapshotted, responded, closed):
        service.record(observation)
    await service.flush_task(task_id)
    return task_id, step_id, missing_block_id, producer


@pytest.mark.anyio
async def test_snapshot_with_permanently_missing_content_remains_queryable_as_incomplete(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-incomplete-context.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()

    try:
        _, step_id, missing_block_id, _ = await _record_incomplete_context(service, source_suffix="permanent")
        context = await service.get_step_context(step_id)
        health = service.get_health()
    finally:
        await service.stop()
        await engine.dispose()

    assert context is not None
    assert context.status == "incomplete"
    assert len(context.items) == 1
    assert context.items[0].ordinal == 0
    assert context.items[0].block_id == missing_block_id
    assert context.items[0].resolution_status == "missing"
    assert context.items[0].payload_available is False
    assert health.failed_jobs == 0
    assert health.snapshot_count == 1
    assert health.snapshot_item_count == 1
    assert health.snapshot_visible_bytes == 7
    assert health.incomplete_snapshot_count == 1
    assert health.missing_content_block_count == 1


@pytest.mark.anyio
async def test_late_content_repairs_an_incomplete_snapshot(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-repaired-context.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()

    try:
        task_id, step_id, missing_block_id, producer = await _record_incomplete_context(service, source_suffix="repaired")
        service.record(
            ObservationEnvelope(
                kind="content.produced",
                occurred_at=datetime.now(UTC),
                task_id=task_id,
                step_id=step_id,
                subject_type="content_block",
                subject_id=missing_block_id,
                producer=producer,
                producer_seq=6,
                source_event_id="incomplete:repaired:content:late",
                correlation_id=task_id,
                payload={
                    "attempt_id": new_id(),
                    "occurrence_ordinal": 0,
                    "kind": "user_input",
                    "content_hash": hashlib.sha256(b"missing").hexdigest(),
                    "body": "missing",
                    "visible_bytes": 7,
                    "estimated_tokens": 2,
                    "sensitivity_flags": [],
                },
            )
        )
        await service.flush_task(task_id)
        context = await service.get_step_context(step_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert context is not None
    assert context.status == "complete"
    assert len(context.items) == 1
    assert context.items[0].block_id == missing_block_id
    assert context.items[0].kind == "user_input"
    assert context.items[0].resolution_status == "available"
    assert context.items[0].payload_available is True


@pytest.mark.anyio
async def test_late_system_request_completes_an_existing_successful_attempt(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-late-request.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = create_sql_ansich_service(session_factory)
    await service.start()
    task_id = new_id()
    attempt_id = new_id()
    operation_id = new_id()
    producer = Producer(name="late-test", version="1", instance_id="late-instance")
    observed_at = datetime.now(UTC)
    service.record(
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id=task_id,
            source_kind="deerflow_run",
            source_id="run-late-request",
            occurred_at=observed_at,
            source_event_id="run:run-late-request:created",
        )
    )
    await service.flush_task(task_id)
    service.record(
        ObservationEnvelope(
            kind="llm.responded",
            occurred_at=observed_at,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=producer,
            producer_seq=1,
            source_event_id="late:responded",
            correlation_id=task_id,
            payload={
                "attempt_no": 1,
                "latency_ms": 7,
                "usage": {"total_tokens": 3},
                "response_metadata": {"finish_reason": "stop"},
            },
        )
    )
    service.record(
        ObservationEnvelope(
            kind="llm.requested",
            occurred_at=observed_at,
            task_id=task_id,
            subject_type="llm_attempt",
            subject_id=attempt_id,
            producer=producer,
            producer_seq=2,
            source_event_id="late:requested",
            correlation_id=task_id,
            payload={
                "attempt_no": 1,
                "snapshot_id": new_id(),
                "actor_kind": "system_operation",
                "operation_id": operation_id,
                "operation_kind": "memory",
                "adapter_name": "test.Adapter",
                "adapter_version": "1",
                "configured_model": "test-model",
            },
        )
    )

    try:
        await service.flush_task(task_id)
        operations = await service.list_system_operations(task_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert len(operations) == 1
    assert operations[0].status == "success"
    assert operations[0].request_obs_id is not None
    assert operations[0].operation_id == operation_id
    assert operations[0].operation_kind == "memory"
    assert operations[0].usage == {"total_tokens": 3}
