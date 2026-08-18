"""Fail-open coverage for the feedback -> Ansich evaluation bridge.

Feedback is a product feature that must keep working whether or not Ansich is
configured, healthy, or observing the run being rated. Every test here drives
the real feedback endpoints over HTTP against a real ``FeedbackRepository`` and
a real SQL-backed ``AnsichService``, so "the evaluation landed" means an
Observation actually reached storage rather than a mock recording a call.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import AnsichService, ObservationEnvelope, new_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import feedback as feedback_router
from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import AnsichObservationRow
from deerflow.persistence.base import Base
from deerflow.persistence.feedback.sql import FeedbackRepository

_THREAD_ID = "thread-feedback-1"
_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
_OCCURRED_AT = datetime(2026, 8, 18, 9, tzinfo=UTC)
_EVALUATION_KIND = "evaluation.recorded"
#: A comment carries the user's own words; it must never reach the Observation.
_COMMENT = "it ignored the deadline i gave in my second message"


def _stub_user() -> User:
    """A stable identity, so a re-rating keeps the same source-event id."""

    return User(id=_USER_ID, email="feedback-evaluation@example.com", password_hash="x", system_role="user")


class _SessionAuthSourceMiddleware(BaseHTTPMiddleware):
    """Stamp the stubbed request's auth provenance.

    ``make_authed_test_app`` stamps the user but not where it came from, and
    ``get_current_user`` only trusts ``request.state.user`` once
    ``auth_source`` says it was authenticated — without this every request
    would resolve as anonymous.
    """

    async def dispatch(self, request, call_next):
        request.state.auth_source = AUTH_SOURCE_SESSION
        return await call_next(request)


def _run_store() -> MagicMock:
    """A run store that reports every requested run as living in the thread."""

    store = MagicMock()
    store.get = AsyncMock(side_effect=lambda run_id: {"run_id": run_id, "thread_id": _THREAD_ID})
    return store


class _FeedbackHarness:
    """The pieces one bridge test needs: a real service, a real repo, a client."""

    def __init__(
        self,
        *,
        service: AnsichService | None,
        session_factory: async_sessionmaker[AsyncSession],
        app: Any,
        client: AsyncClient,
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.app = app
        self.client = client

    async def seed_task(self, *, run_id: str) -> str:
        """Create the Ansich Task the given DeerFlow run maps to."""

        assert self.service is not None
        task_id = new_id()
        self.service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id=run_id,
                occurred_at=_OCCURRED_AT,
                source_event_id=f"run:{run_id}:task:created",
            )
        )
        await self.service.flush_task(task_id)
        return task_id

    async def evaluations(self, *, task_id: str | None = None) -> list[AnsichObservationRow]:
        """Persist any queued Observations for the Task, then read them back."""

        assert self.service is not None
        if task_id is not None:
            await self.service.flush_task(task_id)
        async with self.session_factory() as session:
            rows = await session.execute(
                select(AnsichObservationRow).where(AnsichObservationRow.kind == _EVALUATION_KIND).order_by(AnsichObservationRow.ingest_seq),
            )
            return list(rows.scalars())

    async def put_feedback(self, *, run_id: str, rating: int, comment: str | None = _COMMENT):
        return await self.client.put(
            f"/api/threads/{_THREAD_ID}/runs/{run_id}/feedback",
            json={"rating": rating, "comment": comment},
        )

    async def post_feedback(self, *, run_id: str, rating: int, comment: str | None = _COMMENT):
        return await self.client.post(
            f"/api/threads/{_THREAD_ID}/runs/{run_id}/feedback",
            json={"rating": rating, "comment": comment},
        )


@asynccontextmanager
async def _feedback_harness(
    tmp_path: Path,
    database_name: str,
    *,
    with_ansich: bool = True,
    feedback_repo: Any | None = None,
    authenticated: bool = True,
    ansich_service: Any | None = None,
) -> AsyncIterator[_FeedbackHarness]:
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

    service: AnsichService | None = None
    if ansich_service is None and with_ansich:
        service = create_sql_ansich_service(
            session_factory,
            flush_interval_ms=60_000,
            terminal_flush_timeout_ms=10_000,
            projector_poll_interval_ms=5,
            operations_assessment_interval_ms=60_000,
        )
        await service.start()

    app = make_authed_test_app(user_factory=_stub_user)
    if authenticated:
        app.add_middleware(_SessionAuthSourceMiddleware)
    app.state.feedback_repo = feedback_repo if feedback_repo is not None else FeedbackRepository(session_factory)
    app.state.run_store = _run_store()
    if ansich_service is not None:
        app.state.ansich_service = ansich_service
    elif service is not None:
        app.state.ansich_service = service
    app.include_router(feedback_router.router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield _FeedbackHarness(service=service, session_factory=session_factory, app=app, client=client)
    finally:
        if service is not None:
            await service.stop()
        await engine.dispose()


def _evaluation(row: AnsichObservationRow) -> dict[str, Any]:
    assert row.payload_json is not None
    return row.payload_json["evaluation"]


# ---------------------------------------------------------------------------
# Mapping: a thumb is a relevance judgement, never a correctness one
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_thumbs_up_records_a_soft_relevance_pass_against_the_run_task(tmp_path) -> None:
    async with _feedback_harness(tmp_path, "thumbs_up.db") as harness:
        task_id = await harness.seed_task(run_id="run-up")

        response = await harness.put_feedback(run_id="run-up", rating=1)

        assert response.status_code == 200
        body = response.json()
        assert body["rating"] == 1
        assert body["comment"] == _COMMENT
        assert body["run_id"] == "run-up"
        assert body["thread_id"] == _THREAD_ID

        rows = await harness.evaluations(task_id=task_id)
        assert len(rows) == 1
        row = rows[0]
        assert row.task_id == task_id
        assert row.subject_type == "task"
        assert row.subject_id == task_id
        assert row.producer_name == "ansich-feedback-adapter"
        assert row.producer_version == "1"
        assert row.producer_instance_id == "gateway"
        assert row.source_event_id == f"evaluation:feedback:{_THREAD_ID}:run-up:{_USER_ID}:1"

        evaluation = _evaluation(row)
        assert evaluation["subject_type"] == "task"
        assert evaluation["subject_id"] == task_id
        # The contract requires a Task-subject evaluation to own itself.
        assert evaluation["task_id"] == evaluation["subject_id"]
        assert evaluation["evaluation_kind"] == "user_feedback"
        assert evaluation["dimension"] == "relevance"
        assert evaluation["verdict"] == "pass"
        assert evaluation["fidelity_class"] == "soft"
        assert evaluation["assessor"] == {"name": "user-feedback", "version": "1.0.0"}
        assert evaluation["human_override"] is False

        # The projected index is what quality Beliefs read from.
        assert harness.service is not None
        indexed = await harness.service.list_evaluations(task_id=task_id)
        assert [(item.dimension, item.verdict, item.assessor_name) for item in indexed] == [("relevance", "pass", "user-feedback")]


@pytest.mark.anyio
async def test_thumbs_down_records_a_relevance_fail_and_never_infers_correctness(tmp_path) -> None:
    async with _feedback_harness(tmp_path, "thumbs_down.db") as harness:
        task_id = await harness.seed_task(run_id="run-down")

        response = await harness.post_feedback(run_id="run-down", rating=-1)

        assert response.status_code == 200
        rows = await harness.evaluations(task_id=task_id)
        assert len(rows) == 1
        evaluation = _evaluation(rows[0])
        assert evaluation["verdict"] == "fail"
        assert evaluation["dimension"] == "relevance"
        # A thumb says the answer did not serve the request; it never asserts
        # the answer was factually wrong.
        assert all(_evaluation(row)["dimension"] != "correctness" for row in rows)


@pytest.mark.anyio
async def test_the_free_text_comment_never_reaches_the_observation(tmp_path) -> None:
    async with _feedback_harness(tmp_path, "comment.db") as harness:
        task_id = await harness.seed_task(run_id="run-comment")

        response = await harness.put_feedback(run_id="run-comment", rating=-1, comment=_COMMENT)

        assert response.status_code == 200
        assert response.json()["comment"] == _COMMENT
        rows = await harness.evaluations(task_id=task_id)
        assert len(rows) == 1
        assert _evaluation(rows[0])["rationale"] is None
        assert _COMMENT not in json.dumps(rows[0].payload_json)


@pytest.mark.anyio
async def test_anonymous_feedback_keeps_a_stable_source_event_identity(tmp_path) -> None:
    async with _feedback_harness(tmp_path, "anonymous.db", authenticated=False) as harness:
        task_id = await harness.seed_task(run_id="run-anon")

        response = await harness.put_feedback(run_id="run-anon", rating=1)

        assert response.status_code == 200
        rows = await harness.evaluations(task_id=task_id)
        assert len(rows) == 1
        assert rows[0].source_event_id == f"evaluation:feedback:{_THREAD_ID}:run-anon:anonymous:1"


# ---------------------------------------------------------------------------
# Idempotency: the rating is part of the identity
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resubmitting_the_same_rating_records_one_observation(tmp_path) -> None:
    async with _feedback_harness(tmp_path, "same_rating.db") as harness:
        task_id = await harness.seed_task(run_id="run-same")

        first = await harness.put_feedback(run_id="run-same", rating=1)
        second = await harness.put_feedback(run_id="run-same", rating=1)

        assert (first.status_code, second.status_code) == (200, 200)
        rows = await harness.evaluations(task_id=task_id)
        assert len(rows) == 1
        # A re-clicked thumb is absorbed at the storage layer, so repeating it
        # must not register as loss or a failed projection job.
        assert harness.service is not None
        assert harness.service.get_health().status == "healthy"


@pytest.mark.anyio
async def test_changing_the_rating_records_a_second_observation(tmp_path) -> None:
    async with _feedback_harness(tmp_path, "changed_rating.db") as harness:
        task_id = await harness.seed_task(run_id="run-changed")

        first = await harness.put_feedback(run_id="run-changed", rating=1)
        second = await harness.put_feedback(run_id="run-changed", rating=-1)

        assert (first.status_code, second.status_code) == (200, 200)
        rows = await harness.evaluations(task_id=task_id)
        assert [_evaluation(row)["verdict"] for row in rows] == ["pass", "fail"]
        assert [row.source_event_id for row in rows] == [
            f"evaluation:feedback:{_THREAD_ID}:run-changed:{_USER_ID}:1",
            f"evaluation:feedback:{_THREAD_ID}:run-changed:{_USER_ID}:-1",
        ]


# ---------------------------------------------------------------------------
# Fail-open: Ansich never degrades, delays, or masks the feedback write
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feedback_succeeds_when_no_ansich_service_is_configured(tmp_path, caplog) -> None:
    async with _feedback_harness(tmp_path, "no_ansich.db", with_ansich=False) as harness:
        with caplog.at_level(logging.WARNING):
            response = await harness.put_feedback(run_id="run-no-ansich", rating=1)

        assert response.status_code == 200
        assert response.json()["rating"] == 1
        assert "ansich" not in caplog.text.lower()


@pytest.mark.anyio
@pytest.mark.parametrize("failing_call", ["get_task_by_source", "record"])
async def test_feedback_succeeds_and_warns_when_the_bridge_fails(tmp_path, caplog, failing_call: str) -> None:
    service = MagicMock()
    service.get_task_by_source = AsyncMock(return_value=SimpleNamespace(task_id=new_id()))
    service.record = MagicMock()
    getattr(service, failing_call).side_effect = RuntimeError("ansich is down")

    async with _feedback_harness(tmp_path, f"bridge_fails_{failing_call}.db", ansich_service=service) as harness:
        with caplog.at_level(logging.WARNING, logger="app.gateway.feedback_evaluation"):
            response = await harness.put_feedback(run_id="run-broken", rating=-1)

        assert response.status_code == 200
        assert response.json()["rating"] == -1
        assert "ansich feedback evaluation failed" in caplog.text
        assert "RuntimeError" in caplog.text


@pytest.mark.anyio
async def test_a_run_ansich_never_observed_records_no_evaluation(tmp_path) -> None:
    async with _feedback_harness(tmp_path, "unknown_run.db") as harness:
        # A different run's Task exists, so the lookup is a real miss rather
        # than an empty database.
        known_task_id = await harness.seed_task(run_id="run-known")
        assert harness.service is not None
        accepted_before = harness.service.get_health().accepted_count

        response = await harness.put_feedback(run_id="run-unobserved", rating=1)

        assert response.status_code == 200
        assert harness.service.get_health().accepted_count == accepted_before
        assert await harness.evaluations(task_id=known_task_id) == []


@pytest.mark.anyio
async def test_a_failed_feedback_write_never_invokes_the_bridge(tmp_path, monkeypatch) -> None:
    repo = MagicMock()
    repo.upsert = AsyncMock(side_effect=RuntimeError("feedback write failed"))

    async with _feedback_harness(tmp_path, "primary_write_fails.db", feedback_repo=repo) as harness:
        task_id = await harness.seed_task(run_id="run-write-fails")
        assert harness.service is not None
        accepted_before = harness.service.get_health().accepted_count

        bridge = AsyncMock()
        monkeypatch.setattr(feedback_router, "record_feedback_evaluation", bridge)

        with pytest.raises(RuntimeError, match="feedback write failed"):
            await harness.put_feedback(run_id="run-write-fails", rating=1)

        bridge.assert_not_awaited()
        assert harness.service.get_health().accepted_count == accepted_before
        assert await harness.evaluations(task_id=task_id) == []
