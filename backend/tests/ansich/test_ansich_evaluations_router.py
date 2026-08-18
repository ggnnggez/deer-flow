"""HTTP surface tests for the Phase 10 evaluation and release-quality routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import AnsichService, ObservationEnvelope, Producer, ToolEffect, new_id
from ansich.evaluation import EVALUATION_OBSERVATION_KIND
from ansich.release import AgentRuntimeDescriptor, build_agent_release
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.deps import snapshot_ansich_evaluation_settings
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_embedded_ansich_service, create_sql_ansich_service
from deerflow.ansich.persistence.models import AnsichBeliefAssertionRow, AnsichObservationRow
from deerflow.config.ansich_config import AnsichConfig
from deerflow.persistence.base import Base

_OCCURRED_AT = datetime(2026, 8, 18, 9, tzinfo=UTC)
_OPERATOR_ASSESSOR = {"name": "deerflow-operator", "version": "1.0.0"}
_JUDGE_ASSESSOR = {"name": "ansich-llm-judge", "version": "1.0.0"}
_BENCHMARK_ASSESSOR = {"name": "ansich-benchmark-runner", "version": "1.0.0"}
_UNIT_SCALE = {"min": 0.0, "max": 1.0, "higher_is_better": True}
_COHORT = "ansich-regression@2026.08.1"


def _admin_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-evaluations-admin@example.com",
        password_hash="x",
        system_role="admin",
    )


def _regular_user() -> User:
    return User(
        id=uuid4(),
        email="ansich-evaluations-user@example.com",
        password_hash="x",
        system_role="user",
    )


class _EvaluationHarness:
    """The pieces one router test needs: a real service, its app, and a client."""

    def __init__(self, service: AnsichService, app, client: AsyncClient, session_factory=None) -> None:
        self.service = service
        self.app = app
        self.client = client
        self.session_factory = session_factory

    def set_evaluation_settings(self, config: AnsichConfig) -> None:
        self.app.state.ansich_evaluation_settings = snapshot_ansich_evaluation_settings(config)

    async def count_recorded_evaluations(self) -> int:
        """Count persisted evaluation Observations, whatever their subject."""

        async with self.session_factory() as session:
            return int(await session.scalar(select(func.count()).select_from(AnsichObservationRow).where(AnsichObservationRow.kind == EVALUATION_OBSERVATION_KIND)))

    async def count_quality_assertions(self) -> int:
        """Count persisted ``quality.<dimension>`` assertions, whatever their subject."""

        async with self.session_factory() as session:
            return int(await session.scalar(select(func.count()).select_from(AnsichBeliefAssertionRow).where(AnsichBeliefAssertionRow.field_name.like("quality.%"))))


@asynccontextmanager
async def _evaluation_harness(
    tmp_path: Path,
    database_name: str,
    *,
    ansich_config: AnsichConfig | None = None,
    user_factory=_admin_user,
    **overrides: Any,
) -> AsyncIterator[_EvaluationHarness]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / database_name}",
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
    settings: dict[str, Any] = {
        "flush_interval_ms": 60_000,
        "terminal_flush_timeout_ms": 10_000,
        "projector_poll_interval_ms": 5,
        "operations_assessment_interval_ms": 60_000,
    }
    settings.update(overrides)
    service = create_sql_ansich_service(session_factory, **settings)
    await service.start()
    app = make_authed_test_app(user_factory=user_factory)
    app.state.ansich_service = service
    app.state.ansich_evaluation_settings = snapshot_ansich_evaluation_settings(ansich_config)
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield _EvaluationHarness(service, app, client, session_factory)
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


def _task_started(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.started",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{run_id}:task:started",
    )


def _step_started(task_id: str, step_id: str, *, step_seq: int = 1) -> ObservationEnvelope:
    return ObservationEnvelope(
        kind="step.started",
        occurred_at=_OCCURRED_AT,
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="ansich-step-probe", version="1", instance_id="test"),
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": step_seq, "actor_kind": "lead_agent"},
    )


def _release_resolved(task_id: str, run_id: str, *, model: str) -> ObservationEnvelope:
    return ObservationEnvelope.agent_release_resolved(
        task_id=task_id,
        run_id=run_id,
        occurred_at=_OCCURRED_AT,
        release=build_agent_release(
            AgentRuntimeDescriptor(
                namespace="deerflow",
                agent_name="lead-agent",
                effective_model=model,
                prompt_template_id="lead-v1",
                rendered_base_prompt="You are DeerFlow.",
                effective_policies={"max_steps": 20},
            )
        ),
        source_event_id=f"run:{run_id}:agent-release:resolved",
    )


def _annotation_body(subject_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "subject_type": "task",
        "subject_id": subject_id,
        "evaluation_kind": "developer_annotation",
        "dimension": "correctness",
        "verdict": "pass",
        "assessor": _OPERATOR_ASSESSOR,
        "fidelity_class": "soft",
        "occurred_at": _OCCURRED_AT.isoformat(),
    }
    body.update(overrides)
    return body


def _benchmark_body(subject_id: str, **overrides: Any) -> dict[str, Any]:
    body = _annotation_body(
        subject_id,
        evaluation_kind="benchmark_assertion",
        assessor=_BENCHMARK_ASSESSOR,
        fidelity_class="hard",
        suite="ansich-regression",
        suite_version="2026.08.1",
        case_id="case-1",
        run_id="bench-run-1",
    )
    body.update(overrides)
    return body


async def _open_tool_frequency_alert(service: AnsichService, *, task_id: str, run_id: str, tool_name: str) -> None:
    """Produce one operational Alert whose subject is the given Task."""

    step_id = new_id()
    tool_call_id = new_id()
    producer = Producer(name="ansich-evaluations-router-test", version="1", instance_id="test")
    service.record_batch(
        (
            _task_created(task_id, run_id),
            _task_started(task_id, run_id),
            _step_started(task_id, step_id),
            ObservationEnvelope(
                kind="tool.issued",
                occurred_at=_OCCURRED_AT,
                task_id=task_id,
                step_id=step_id,
                subject_type="tool_call",
                subject_id=tool_call_id,
                producer=producer,
                source_event_id=f"run:{run_id}:tool:issued",
                correlation_id=task_id,
                payload={
                    "call_seq": 1,
                    "provider_call_id": f"provider-{run_id}",
                    "tool_name": tool_name,
                    "args_hash": "a" * 64,
                    "args_preview": {"query": "status"},
                    "tool_schema_block_id": None,
                },
            ),
        )
    )
    await service.flush_task(task_id)
    await service.assess_operations(now=_OCCURRED_AT + timedelta(seconds=1))


async def _open_unverified_effect_alert(service: AnsichService, *, task_id: str, run_id: str) -> str:
    """Produce one scope-safety Alert whose subject is a ToolCall, not the Task.

    ``assess_scope_safety`` asserts on the ``tool_call_id`` (scope_safety.py:120),
    so every scope-safety Alert type carries a ToolCall subject. An intended
    effect with no observed counterpart and no authorization snapshot is the
    cheapest of them: ``unverified_effect`` is ``present``.
    """

    step_id = new_id()
    tool_call_id = new_id()
    effect_obs_id = new_id()
    producer = Producer(name="ansich-evaluations-router-test", version="1", instance_id="test")
    effect = ToolEffect(
        effect_id=new_id(),
        tool_call_id=tool_call_id,
        effect_class="filesystem_write",
        phase="intended",
        target_preview="workspace/report.md",
        fidelity_class="declared",
        source_obs_id=effect_obs_id,
    )
    service.record_batch(
        (
            _task_created(task_id, run_id),
            _task_started(task_id, run_id),
            _step_started(task_id, step_id),
            ObservationEnvelope(
                kind="tool.issued",
                occurred_at=_OCCURRED_AT,
                task_id=task_id,
                step_id=step_id,
                subject_type="tool_call",
                subject_id=tool_call_id,
                producer=producer,
                source_event_id=f"run:{run_id}:tool:issued",
                correlation_id=task_id,
                payload={
                    "call_seq": 1,
                    "provider_call_id": f"provider-{run_id}",
                    "tool_name": "write_file",
                    "args_hash": "b" * 64,
                    "args_preview": {"path": "workspace/report.md"},
                    "tool_schema_block_id": None,
                },
            ),
            ObservationEnvelope(
                obs_id=effect_obs_id,
                kind="effect.intended",
                occurred_at=_OCCURRED_AT,
                task_id=task_id,
                step_id=step_id,
                subject_type="effect",
                subject_id=effect.effect_id,
                producer=producer,
                source_event_id=f"run:{run_id}:effect:intended",
                correlation_id=task_id,
                payload={"effect": effect.model_dump(mode="json")},
            ),
        )
    )
    await service.flush_task(task_id)
    await service.assess_operations(now=_OCCURRED_AT + timedelta(seconds=1))
    return tool_call_id


# ---------------------------------------------------------------------------
# Authorization and availability
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluation_endpoints_are_admin_only() -> None:
    service = AnsichService.in_memory()
    await service.start()
    app = make_authed_test_app(user_factory=_regular_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            posted = await client.post(
                "/api/ansich/evaluations",
                headers={"Idempotency-Key": "forbidden"},
                json=_annotation_body(new_id()),
            )
            task_evaluations = await client.get(f"/api/ansich/tasks/{new_id()}/evaluations")
            step_evaluations = await client.get(f"/api/ansich/steps/{new_id()}/evaluations")
            evaluation_payload = await client.get(f"/api/ansich/evaluations/{new_id()}/payload")
            release_quality = await client.get(f"/api/ansich/agent-releases/{new_id()}/quality")
    finally:
        await service.stop()

    assert posted.status_code == 403
    assert task_evaluations.status_code == 403
    assert step_evaluations.status_code == 403
    assert evaluation_payload.status_code == 403
    assert release_quality.status_code == 403


@pytest.mark.anyio
async def test_evaluation_endpoints_are_503_without_an_ansich_service() -> None:
    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = None
    app.include_router(ansich_router.router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        posted = await client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "disabled"},
            json=_annotation_body(new_id()),
        )
        task_evaluations = await client.get(f"/api/ansich/tasks/{new_id()}/evaluations")
        step_evaluations = await client.get(f"/api/ansich/steps/{new_id()}/evaluations")
        evaluation_payload = await client.get(f"/api/ansich/evaluations/{new_id()}/payload")
        release_quality = await client.get(f"/api/ansich/agent-releases/{new_id()}/quality")

    for response in (posted, task_evaluations, step_evaluations, evaluation_payload, release_quality):
        assert response.status_code == 503
        assert response.json()["detail"] == "Ansich is disabled or unavailable"


@pytest.mark.anyio
async def test_evaluation_endpoints_are_503_when_storage_is_unavailable() -> None:
    service = create_embedded_ansich_service(AnsichConfig(enabled=True), None)
    assert service is not None
    await service.start()
    app = make_authed_test_app(user_factory=_admin_user)
    app.state.ansich_service = service
    app.include_router(ansich_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            posted = await client.post(
                "/api/ansich/evaluations",
                headers={"Idempotency-Key": "storage-down"},
                json=_annotation_body(new_id()),
            )
            task_evaluations = await client.get(f"/api/ansich/tasks/{new_id()}/evaluations")
            step_evaluations = await client.get(f"/api/ansich/steps/{new_id()}/evaluations")
            evaluation_payload = await client.get(f"/api/ansich/evaluations/{new_id()}/payload")
            release_quality = await client.get(f"/api/ansich/agent-releases/{new_id()}/quality")
    finally:
        await service.stop()

    for response in (posted, task_evaluations, step_evaluations, evaluation_payload, release_quality):
        assert response.status_code == 503
        assert response.json()["detail"]["projection_status"]["status"] == "failed"


# ---------------------------------------------------------------------------
# POST /api/ansich/evaluations
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_evaluation_records_the_record_and_replays_the_idempotency_key(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-router-post"

    async with _evaluation_harness(tmp_path, "ansich-evaluations-post.db") as harness:
        harness.service.record(_task_created(task_id, run_id))
        await harness.service.flush_task(task_id)

        first = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-post-1"},
            json=_annotation_body(task_id, rationale="reviewed the final answer"),
        )
        replay = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-post-1"},
            json=_annotation_body(task_id, rationale="reviewed the final answer"),
        )
        listed = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

    assert first.status_code == 200
    assert set(first.json()) == {"observation_id", "projection_status", "idempotent_replay"}
    assert first.json()["projection_status"] == "applied"
    assert first.json()["idempotent_replay"] is False
    assert replay.status_code == 200
    assert replay.json()["observation_id"] == first.json()["observation_id"]
    assert replay.json()["idempotent_replay"] is True
    assert listed.status_code == 200
    assert [item["evaluation_obs_id"] for item in listed.json()["evaluations"]] == [first.json()["observation_id"]]
    assert listed.json()["evaluations"][0]["authority_class"] == "soft_human"


@pytest.mark.anyio
async def test_post_benchmark_evaluation_replays_on_its_suite_tuple_not_the_header(tmp_path) -> None:
    """A benchmark evaluation's replay identity is its suite/case/run tuple (Task 1)."""

    task_id, run_id = new_id(), "eval-router-benchmark"

    async with _evaluation_harness(tmp_path, "ansich-evaluations-benchmark.db") as harness:
        harness.service.record(_task_created(task_id, run_id))
        await harness.service.flush_task(task_id)

        first = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "benchmark-key-a"},
            json=_benchmark_body(task_id),
        )
        other_key = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "benchmark-key-b"},
            json=_benchmark_body(task_id),
        )
        without_run = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "benchmark-key-c"},
            json=_benchmark_body(task_id, run_id=None, case_id="case-2"),
        )

    assert first.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert other_key.status_code == 200
    assert other_key.json()["observation_id"] == first.json()["observation_id"]
    assert other_key.json()["idempotent_replay"] is True
    assert without_run.status_code == 422
    assert "run_id" in str(without_run.json()["detail"])


@pytest.mark.anyio
async def test_post_evaluation_404s_an_unknown_subject(tmp_path) -> None:
    async with _evaluation_harness(tmp_path, "ansich-evaluations-unknown-subject.db") as harness:
        response = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-unknown"},
            json=_annotation_body(new_id()),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Ansich evaluation subject not found"


@pytest.mark.anyio
async def test_post_evaluation_413s_a_payload_over_the_startup_snapshot_limit(tmp_path) -> None:
    """The limit comes from the lifespan snapshot, never a live config read."""

    task_id, run_id = new_id(), "eval-router-oversize"

    async with _evaluation_harness(
        tmp_path,
        "ansich-evaluations-oversize.db",
        ansich_config=AnsichConfig(enabled=True, evaluation_max_payload_bytes=1_024),
    ) as harness:
        harness.service.record(_task_created(task_id, run_id))
        await harness.service.flush_task(task_id)

        oversized = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-oversize"},
            json=_annotation_body(task_id, rationale="x" * 4_000),
        )
        accepted = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-within-limit"},
            json=_annotation_body(task_id, rationale="x" * 16),
        )

    assert oversized.status_code == 413
    assert accepted.status_code == 200


@pytest.mark.anyio
async def test_post_evaluation_422s_invalid_requests(tmp_path) -> None:
    task_id, run_id, step_id = new_id(), "eval-router-invalid", new_id()

    async with _evaluation_harness(tmp_path, "ansich-evaluations-invalid.db") as harness:
        harness.service.record_batch((_task_created(task_id, run_id), _step_started(task_id, step_id)))
        await harness.service.flush_task(task_id)

        missing_key = await harness.client.post(
            "/api/ansich/evaluations",
            json=_annotation_body(task_id),
        )
        blank_key = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "   "},
            json=_annotation_body(task_id),
        )
        long_key = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "k" * 129},
            json=_annotation_body(task_id),
        )
        score_without_scale = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-score"},
            json=_annotation_body(task_id, verdict=None, score=0.5),
        )
        judge_override = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-judge"},
            json=_annotation_body(
                task_id,
                evaluation_kind="llm_judge",
                assessor=_JUDGE_ASSESSOR,
                human_override=True,
            ),
        )
        conflicting_task_id = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-conflicting-task"},
            json=_annotation_body(task_id, task_id=new_id()),
        )
        step_without_task = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-step-no-task"},
            json=_annotation_body(step_id, subject_type="step"),
        )
        # A real Step id submitted as a Task subject: the entity exists, so the
        # refusal must come from the subject-type cross-check, not a 404.
        subject_type_mismatch = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-subject-mismatch"},
            json=_annotation_body(step_id),
        )
        # A misspelled field must be reported, never silently dropped.
        unknown_field = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-unknown-field"},
            json=_annotation_body(task_id, rationale_text="typo"),
        )

    for response in (
        missing_key,
        blank_key,
        long_key,
        score_without_scale,
        judge_override,
        conflicting_task_id,
        step_without_task,
        subject_type_mismatch,
        unknown_field,
    ):
        assert response.status_code == 422, response.text
    assert "scale" in str(score_without_scale.json()["detail"])
    assert "human_override" in str(judge_override.json()["detail"])
    assert "task_id" in str(conflicting_task_id.json()["detail"])
    assert "task_id" in str(step_without_task.json()["detail"])
    assert subject_type_mismatch.json()["detail"] == "Ansich evaluation subject is a step, not a task"


# ---------------------------------------------------------------------------
# GET /api/ansich/tasks/{task_id}/evaluations
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_task_evaluations_report_unassessed_then_resolved_quality_beliefs(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-router-task-read"

    async with _evaluation_harness(tmp_path, "ansich-evaluations-task-read.db") as harness:
        harness.service.record(_task_created(task_id, run_id))
        await harness.service.flush_task(task_id)

        unknown = await harness.client.get(f"/api/ansich/tasks/{new_id()}/evaluations")
        before = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

        judged = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-task-judge"},
            json=_annotation_body(
                task_id,
                evaluation_kind="llm_judge",
                assessor=_JUDGE_ASSESSOR,
                verdict="fail",
            ),
        )
        annotated = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-task-annotation"},
            json=_annotation_body(task_id, verdict="pass"),
        )
        after = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Ansich Task not found"
    assert before.status_code == 200
    assert before.json()["task_id"] == task_id
    assert before.json()["evaluations"] == []
    assert [belief["dimension"] for belief in before.json()["quality_beliefs"]] == [
        "correctness",
        "completeness",
        "relevance",
        "safety",
        "efficiency",
    ]
    assert all(belief["unassessed"] is True for belief in before.json()["quality_beliefs"])
    assert before.json()["projection_status"]["status"] in {"healthy", "degraded"}
    assert judged.status_code == 200
    assert annotated.status_code == 200
    assert after.status_code == 200
    assert len(after.json()["evaluations"]) == 2
    beliefs = {belief["dimension"]: belief for belief in after.json()["quality_beliefs"]}
    assert beliefs["correctness"]["unassessed"] is False
    assert beliefs["correctness"]["value"]["verdict"] == "pass"
    assert beliefs["correctness"]["authority_class"] == "soft_human"
    assert beliefs["correctness"]["conflicting_assertion_count"] == 1
    assert beliefs["safety"]["unassessed"] is True


# ---------------------------------------------------------------------------
# GET /api/ansich/evaluations/{obs_id}/payload
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluation_payload_serves_expected_actual_lazily_and_no_store(tmp_path) -> None:
    """The bodies the index deliberately omits are readable only through this route."""

    task_id, run_id = new_id(), "eval-router-payload"
    created = _task_created(task_id, run_id)

    async with _evaluation_harness(tmp_path, "ansich-evaluations-payload.db") as harness:
        harness.service.record(created)
        await harness.service.flush_task(task_id)

        recorded = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-payload-1"},
            json=_annotation_body(
                task_id,
                verdict="fail",
                expected="a cited answer",
                actual="an uncited answer",
                rationale="no source was named",
            ),
        )
        obs_id = recorded.json()["observation_id"]

        payload = await harness.client.get(f"/api/ansich/evaluations/{obs_id}/payload")
        unknown = await harness.client.get(f"/api/ansich/evaluations/{new_id()}/payload")
        not_an_evaluation = await harness.client.get(f"/api/ansich/evaluations/{created.obs_id}/payload")
        listed = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

    assert recorded.status_code == 200
    assert payload.status_code == 200
    assert payload.headers["cache-control"] == "no-store"
    body = payload.json()
    assert body["evaluation_obs_id"] == obs_id
    evaluation = body["payload"]["evaluation"]
    assert evaluation["expected"] == "a cited answer"
    assert evaluation["actual"] == "an uncited answer"
    assert evaluation["rationale"] == "no source was named"
    # The polled index carries none of those bodies.
    assert listed.status_code == 200
    assert set(listed.json()["evaluations"][0]) & {"expected", "actual", "rationale"} == set()
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Ansich evaluation payload not found"
    assert not_an_evaluation.status_code == 404
    assert not_an_evaluation.json()["detail"] == "Ansich evaluation payload not found"


# ---------------------------------------------------------------------------
# GET /api/ansich/steps/{step_id}/evaluations
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_step_evaluations_404_unknown_steps_and_list_step_subjects(tmp_path) -> None:
    task_id, run_id, step_id = new_id(), "eval-router-step-read", new_id()

    async with _evaluation_harness(tmp_path, "ansich-evaluations-step-read.db") as harness:
        harness.service.record_batch((_task_created(task_id, run_id), _step_started(task_id, step_id)))
        await harness.service.flush_task(task_id)

        unknown = await harness.client.get(f"/api/ansich/steps/{new_id()}/evaluations")
        not_a_step = await harness.client.get(f"/api/ansich/steps/{task_id}/evaluations")
        recorded = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-step"},
            json=_annotation_body(
                step_id,
                subject_type="step",
                task_id=task_id,
                dimension="relevance",
                verdict="partial",
            ),
        )
        listed = await harness.client.get(f"/api/ansich/steps/{step_id}/evaluations")

    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Ansich Step not found"
    assert not_a_step.status_code == 404
    assert recorded.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["step_id"] == step_id
    assert [item["evaluation_obs_id"] for item in listed.json()["evaluations"]] == [recorded.json()["observation_id"]]
    assert listed.json()["evaluations"][0]["subject_type"] == "step"
    assert listed.json()["evaluations"][0]["task_id"] == task_id
    assert listed.json()["projection_status"]["storage_available"] is True


# ---------------------------------------------------------------------------
# GET /api/ansich/agent-releases/{release_id}/quality
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_release_quality_404s_unknown_releases_and_filters_by_cohort(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-router-release-quality"

    async with _evaluation_harness(tmp_path, "ansich-evaluations-release-quality.db") as harness:
        harness.service.record_batch(
            (
                _task_created(task_id, run_id),
                _release_resolved(task_id, run_id, model="provider/model-v1"),
            )
        )
        await harness.service.flush_task(task_id)
        binding = await harness.service.get_task_agent_release(task_id)
        assert binding is not None
        release_id = binding.release.summary.release_id

        recorded = await harness.client.post(
            "/api/ansich/evaluations",
            headers={"Idempotency-Key": "eval-router-release-sample"},
            json=_benchmark_body(task_id, score=1.0, scale=_UNIT_SCALE),
        )
        unknown = await harness.client.get(f"/api/ansich/agent-releases/{new_id()}/quality")
        everything = await harness.client.get(f"/api/ansich/agent-releases/{release_id}/quality")
        matching = await harness.client.get(
            f"/api/ansich/agent-releases/{release_id}/quality",
            params={"cohort": _COHORT},
        )
        other = await harness.client.get(
            f"/api/ansich/agent-releases/{release_id}/quality",
            params={"cohort": "ansich-regression@2026.09.1"},
        )

    assert recorded.status_code == 200
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Ansich AgentRelease not found"
    assert everything.status_code == 200
    assert everything.json()["release_id"] == release_id
    assert [cohort["cohort_key"] for cohort in everything.json()["cohorts"]] == [_COHORT]
    assert everything.json()["cohorts"][0]["dimension"] == "correctness"
    assert everything.json()["cohorts"][0]["assessed_count"] == 1
    assert everything.json()["projection_status"]["storage_available"] is True
    assert matching.status_code == 200
    assert len(matching.json()["cohorts"]) == 1
    assert other.status_code == 200
    assert other.json()["cohorts"] == []


# ---------------------------------------------------------------------------
# GET /api/ansich/agent-releases/compare
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_release_compare_carries_a_quality_block_with_comparability_reasons(tmp_path) -> None:
    left_task, right_task = new_id(), new_id()

    async with _evaluation_harness(tmp_path, "ansich-evaluations-compare.db") as harness:
        for task_id, run_id, model in (
            (left_task, "eval-router-compare-left", "provider/model-v1"),
            (right_task, "eval-router-compare-right", "provider/model-v2"),
        ):
            harness.service.record_batch(
                (
                    _task_created(task_id, run_id),
                    _release_resolved(task_id, run_id, model=model),
                )
            )
            await harness.service.flush_task(task_id)
        bindings = [await harness.service.get_task_agent_release(task_id) for task_id in (left_task, right_task)]
        assert all(binding is not None for binding in bindings)
        left_release, right_release = (binding.release.summary.release_id for binding in bindings)

        # No evaluation on either release: the compare still answers, with no
        # quality comparisons rather than a 404.
        empty = await harness.client.get(
            "/api/ansich/agent-releases/compare",
            params={"left": left_release, "right": right_release},
        )

        for index, task_id in enumerate((left_task, right_task)):
            recorded = await harness.client.post(
                "/api/ansich/evaluations",
                headers={"Idempotency-Key": f"eval-router-compare-{index}"},
                json=_benchmark_body(
                    task_id,
                    score=1.0 if index == 0 else 0.5,
                    scale=_UNIT_SCALE,
                    case_id=f"case-{index}",
                    run_id=f"bench-run-{index}",
                ),
            )
            assert recorded.status_code == 200

        insufficient = await harness.client.get(
            "/api/ansich/agent-releases/compare",
            params={"left": left_release, "right": right_release, "cohort": _COHORT},
        )
        harness.set_evaluation_settings(AnsichConfig(enabled=True, evaluation_min_cohort_samples=1))
        comparable = await harness.client.get(
            "/api/ansich/agent-releases/compare",
            params={"left": left_release, "right": right_release},
        )

    assert empty.status_code == 200
    assert empty.json()["comparison"]["changed_components"]
    assert empty.json()["quality"] == {"comparisons": [], "cohort": None}
    assert insufficient.status_code == 200
    assert insufficient.json()["quality"]["cohort"] == _COHORT
    assert [item["reason"] for item in insufficient.json()["quality"]["comparisons"]] == ["insufficient_samples"]
    assert insufficient.json()["quality"]["comparisons"][0]["comparison_status"] == "not_comparable"
    assert insufficient.json()["quality"]["comparisons"][0]["coverage"]["min_samples"] == 5
    assert comparable.status_code == 200
    assert comparable.json()["quality"]["cohort"] is None
    assert comparable.json()["quality"]["comparisons"][0]["comparison_status"] == "comparable"
    assert comparable.json()["quality"]["comparisons"][0]["observed_delta"] == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# Alert dismissal semantic override (spec section 5)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_plain_alert_dismissal_never_changes_quality_beliefs(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-router-plain-dismiss"

    async with _evaluation_harness(
        tmp_path,
        "ansich-evaluations-plain-dismiss.db",
        tool_frequency_threshold=1,
    ) as harness:
        await _open_tool_frequency_alert(
            harness.service,
            task_id=task_id,
            run_id=run_id,
            tool_name="web_search",
        )
        listed = await harness.client.get("/api/ansich/operations/alerts", params={"task": task_id})
        alert_id = listed.json()["items"][0]["alert_id"]
        acknowledged = await harness.client.post(
            f"/api/ansich/operations/alerts/{alert_id}/acknowledge",
            json={"workflow_version": 1},
        )
        dismissed = await harness.client.post(
            f"/api/ansich/operations/alerts/{alert_id}/dismiss",
            json={"workflow_version": 2, "reason": "expected maintenance traffic"},
        )
        evaluations = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

    assert acknowledged.status_code == 200
    assert "semantic_override" not in acknowledged.json()
    assert dismissed.status_code == 200
    assert dismissed.json()["alert"]["workflow_state"] == "dismissed"
    assert "semantic_override" not in dismissed.json()
    assert evaluations.status_code == 200
    assert evaluations.json()["evaluations"] == []
    assert all(belief["unassessed"] is True for belief in evaluations.json()["quality_beliefs"])


@pytest.mark.anyio
async def test_alert_dismissal_with_a_semantic_override_records_a_human_assertion(tmp_path) -> None:
    task_id, run_id = new_id(), "eval-router-override-dismiss"

    async with _evaluation_harness(
        tmp_path,
        "ansich-evaluations-override-dismiss.db",
        tool_frequency_threshold=1,
    ) as harness:
        await _open_tool_frequency_alert(
            harness.service,
            task_id=task_id,
            run_id=run_id,
            tool_name="web_search",
        )
        listed = await harness.client.get("/api/ansich/operations/alerts", params={"task": task_id})
        alert_id = listed.json()["items"][0]["alert_id"]
        dismissed = await harness.client.post(
            f"/api/ansich/operations/alerts/{alert_id}/dismiss",
            json={
                "workflow_version": 1,
                "reason": "expected maintenance traffic",
                "semantic_override": {
                    "dimension": "safety",
                    "verdict": "pass",
                    "rationale": "operator confirmed the traffic was authorized",
                },
            },
        )
        evaluations = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

    assert dismissed.status_code == 200
    assert dismissed.json()["alert"]["workflow_state"] == "dismissed"
    override = dismissed.json()["semantic_override"]
    assert override["status"] == "recorded"
    assert override["evaluation"]["projection_status"] == "applied"
    assert override["evaluation"]["idempotent_replay"] is False
    assert evaluations.status_code == 200
    assert [item["evaluation_obs_id"] for item in evaluations.json()["evaluations"]] == [override["evaluation"]["observation_id"]]
    assert evaluations.json()["evaluations"][0]["evaluation_kind"] == "developer_annotation"
    assert evaluations.json()["evaluations"][0]["dimension"] == "safety"
    assert evaluations.json()["evaluations"][0]["authority_class"] == "human_override"
    beliefs = {belief["dimension"]: belief for belief in evaluations.json()["quality_beliefs"]}
    assert beliefs["safety"]["unassessed"] is False
    assert beliefs["safety"]["value"]["verdict"] == "pass"
    assert beliefs["safety"]["authority_class"] == "human_override"
    assert beliefs["correctness"]["unassessed"] is True


@pytest.mark.anyio
async def test_a_failing_semantic_override_never_fails_the_dismissal(tmp_path, monkeypatch) -> None:
    task_id, run_id = new_id(), "eval-router-override-degraded"

    async with _evaluation_harness(
        tmp_path,
        "ansich-evaluations-override-degraded.db",
        tool_frequency_threshold=1,
    ) as harness:
        await _open_tool_frequency_alert(
            harness.service,
            task_id=task_id,
            run_id=run_id,
            tool_name="web_search",
        )
        listed = await harness.client.get("/api/ansich/operations/alerts", params={"task": task_id})
        alert_id = listed.json()["items"][0]["alert_id"]

        async def fail_record_evaluation(*args, **kwargs):
            raise RuntimeError("evaluation storage unavailable")

        monkeypatch.setattr(harness.service, "record_evaluation", fail_record_evaluation)
        dismissed = await harness.client.post(
            f"/api/ansich/operations/alerts/{alert_id}/dismiss",
            json={
                "workflow_version": 1,
                "reason": "expected maintenance traffic",
                "semantic_override": {"dimension": "safety", "verdict": "pass"},
            },
        )
        monkeypatch.undo()
        evaluations = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

    assert dismissed.status_code == 200
    assert dismissed.json()["alert"]["workflow_state"] == "dismissed"
    assert dismissed.json()["semantic_override"]["status"] == "degraded"
    assert dismissed.json()["semantic_override"]["evaluation"] is None
    assert evaluations.json()["evaluations"] == []


@pytest.mark.anyio
async def test_a_tool_call_subject_alert_degrades_its_semantic_override(tmp_path) -> None:
    """A scope-safety Alert cannot be overridden into a Task-level quality Belief.

    Overriding hard safety evidence is deliberately out of v1 scope: the Alert's
    subject is a ToolCall, so the override degrades with a marker instead of
    attaching ``quality.<dimension>`` to a ToolCall id. Without this guard the
    dismissal would still return 200 and every other test would stay green.
    """

    task_id, run_id = new_id(), "eval-router-tool-call-subject"

    async with _evaluation_harness(
        tmp_path,
        "ansich-evaluations-tool-call-subject.db",
    ) as harness:
        tool_call_id = await _open_unverified_effect_alert(
            harness.service,
            task_id=task_id,
            run_id=run_id,
        )
        # The `task` filter matches the Alert's subject, and this Alert's
        # subject is exactly what makes it interesting: a ToolCall.
        listed = await harness.client.get(
            "/api/ansich/operations/alerts",
            params={"type": "unverified_effect"},
        )
        alert = listed.json()["items"][0]
        evaluations_before = await harness.count_recorded_evaluations()
        assertions_before = await harness.count_quality_assertions()
        dismissed = await harness.client.post(
            f"/api/ansich/operations/alerts/{alert['alert_id']}/dismiss",
            json={
                "workflow_version": alert["workflow_version"],
                "reason": "the write was reviewed by hand",
                "semantic_override": {
                    "dimension": "safety",
                    "verdict": "pass",
                    "rationale": "operator confirmed the intended write stayed in scope",
                },
            },
        )
        evaluations_after = await harness.count_recorded_evaluations()
        assertions_after = await harness.count_quality_assertions()
        task_evaluations = await harness.client.get(f"/api/ansich/tasks/{task_id}/evaluations")

    assert alert["subject_id"] == tool_call_id
    assert dismissed.status_code == 200
    assert dismissed.json()["alert"]["workflow_state"] == "dismissed"
    assert dismissed.json()["semantic_override"] == {
        "status": "degraded",
        "reason": "alert_subject_is_not_a_task",
        "evaluation": None,
    }
    assert (evaluations_after, assertions_after) == (evaluations_before, assertions_before)
    assert (evaluations_after, assertions_after) == (0, 0)
    assert task_evaluations.json()["evaluations"] == []
    assert all(belief["unassessed"] is True for belief in task_evaluations.json()["quality_beliefs"])
