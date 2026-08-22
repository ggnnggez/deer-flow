"""§7 raw-payload read audit: fail-closed, and the reasons it is.

Task 12 of the P11-C batch. Four HTTP routes return raw bodies — the release
manifest, an evaluation's expected/actual/rationale, a ToolCall's raw or
visible result, and a ContentBlock's payload — and this is the one place in the
batch where a collection failure **refuses the product feature** instead of
degrading (spec:114, plan Global Constraint 1 and ruling RC9). Everything in
this file exists to pin one of the two halves of that:

* the audit is written **before** the body is read, synchronously, and a write
  that does not land means the body is never read at all (503);
* what the audit records is who/what/why/which-request/when — and never the
  bytes.

Where a test could pass by accident, it is instrumented rather than inferred:
the "denied" and "audit unavailable" cases count *calls into the read path*, so
"no payload was returned" cannot stand in for "no payload was read".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest
from _router_auth_helpers import make_authed_test_app
from ansich import AnsichService, ObservationEnvelope, Producer, new_id
from ansich.contracts import ANSICH_BOOTSTRAP_TASK_ID
from ansich.errors import PayloadExpiredError, RawReadAuditUnavailableError
from ansich.operator import RAW_PAYLOAD_READ_ACTION, OperatorAuditActionType, TaskOperatorActionType
from ansich.safety import host_scope_id
from ansich.serialization import serialize_observed_content
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.deps import snapshot_ansich_raw_read_settings
from app.gateway.routers import ansich as ansich_router
from deerflow.ansich import create_sql_ansich_service
from deerflow.ansich.persistence.models import AnsichObservationRow
from deerflow.config.ansich_config import AnsichConfig
from deerflow.persistence.base import Base

_OCCURRED_AT = datetime(2026, 8, 23, 9, tzinfo=UTC)
_ADMIN_ID = UUID("11111111-1111-4111-8111-111111111111")
_REGULAR_ID = UUID("22222222-2222-4222-8222-222222222222")


def _admin_user() -> User:
    return User(id=_ADMIN_ID, email="raw-read-admin@example.com", password_hash="x", system_role="admin")


def _regular_user() -> User:
    return User(id=_REGULAR_ID, email="raw-read-user@example.com", password_hash="x", system_role="user")


@dataclass
class _ReadProbe:
    """A counter wrapped around a service read, so "never read" is observable.

    Asserting on the response alone cannot tell "the payload was not read" from
    "the payload was read and then withheld", and those are different security
    claims. Every test that says the body was never touched installs one of
    these and asserts the count is zero.
    """

    calls: int = 0

    def wrap(self, service: AnsichService, attribute: str) -> None:
        original = getattr(service, attribute)

        async def _counting(*args: Any, **kwargs: Any):
            self.calls += 1
            return await original(*args, **kwargs)

        setattr(service, attribute, _counting)


class _RawReadHarness:
    def __init__(self, service: AnsichService, app, client: AsyncClient, session_factory) -> None:
        self.service = service
        self.app = app
        self.client = client
        self.session_factory = session_factory

    def set_raw_read_settings(self, config: AnsichConfig) -> None:
        self.app.state.ansich_raw_read_settings = snapshot_ansich_raw_read_settings(config)

    async def audit_rows(self) -> list[AnsichObservationRow]:
        """Every §7 audit row in the store, in ingest order."""

        async with self.session_factory() as session:
            rows = (await session.execute(select(AnsichObservationRow).where(AnsichObservationRow.kind.like("operator.action_%")).order_by(AnsichObservationRow.ingest_seq))).scalars()
            return [row for row in rows if (row.payload_json or {}).get("action_type") == RAW_PAYLOAD_READ_ACTION]

    async def audit_payloads(self) -> list[dict]:
        return [row.payload_json for row in await self.audit_rows()]


@asynccontextmanager
async def _harness(
    tmp_path: Path,
    database_name: str = "ansich-raw-read.db",
    *,
    user_factory=_admin_user,
    ansich_config: AnsichConfig | None = None,
) -> AsyncIterator[_RawReadHarness]:
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
    service = create_sql_ansich_service(
        session_factory,
        flush_interval_ms=60_000,
        terminal_flush_timeout_ms=10_000,
        projector_poll_interval_ms=5,
        operations_assessment_interval_ms=60_000,
    )
    await service.start()
    app = make_authed_test_app(user_factory=user_factory)
    app.state.ansich_service = service
    app.state.ansich_raw_read_settings = snapshot_ansich_raw_read_settings(ansich_config)
    app.include_router(ansich_router.router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            harness = _RawReadHarness(service, app, client, session_factory)
            # The host-`Scope` mint `start()` writes is an Observation; the
            # entity these tests subject rows to exists only once it is
            # projected.
            await _settle(harness)
            yield harness
    finally:
        await service.stop()
        await engine.dispose()


async def _settle(harness: _RawReadHarness, *, rounds: int = 20) -> None:
    """Drain projection in bounded rounds against a *condition*, never a clock.

    Every subject these tests assert on — the host ``Scope`` entity, the
    ContentBlock's owning Task — is a projection, and the service's own
    projector loop would get there on its own schedule. Waiting on that
    schedule is the F10-30 shape (a settle budget losing to load); driving the
    claim here and re-reading ``unsettled_job_count`` is not a budget at all.
    """

    backend = harness.service._backend  # type: ignore[attr-defined]
    for _ in range(max(rounds, 1)):
        while await backend.project_pending(limit=200):
            pass
        if await backend.unsettled_job_count() == 0:
            return
    raise AssertionError("projection did not settle in the bounded rounds")


def _task_created(task_id: str, run_id: str) -> ObservationEnvelope:
    return ObservationEnvelope.task_lifecycle(
        kind="task.created",
        task_id=task_id,
        source_kind="deerflow_run",
        source_id=run_id,
        occurred_at=_OCCURRED_AT,
        source_event_id=f"run:{run_id}:task:created",
    )


def _content_produced(task_id: str, *, body: object, ordinal: int = 1, content_kind: str = "tool_result_raw") -> ObservationEnvelope:
    capture = serialize_observed_content(kind=content_kind, body=body, path=f"raw-read:{ordinal}")  # type: ignore[arg-type]
    return ObservationEnvelope(
        kind="content.produced",
        occurred_at=_OCCURRED_AT,
        task_id=task_id,
        subject_type="content_block",
        subject_id=capture.block.block_id,
        producer=Producer(name="raw-read-test", version="1", instance_id="test"),
        producer_seq=ordinal,
        source_event_id=f"raw-read:content:{ordinal}",
        correlation_id=task_id,
        payload=capture.block.model_dump(mode="json"),
    )


async def _planted_block(harness: _RawReadHarness, *, body: object = None) -> tuple[str, str]:
    """One projected Task with one readable ContentBlock. Returns ``(task, block)``."""

    task_id, run_id = new_id(), "raw-read-run"
    block = _content_produced(task_id, body=body if body is not None else {"content": "the raw body"})
    harness.service.record_batch((_task_created(task_id, run_id), block))
    await harness.service.flush_task(task_id)
    await _settle(harness)
    return task_id, block.subject_id


# ---------------------------------------------------------------------------
# The Literal and the envelope contract (RC8)
# ---------------------------------------------------------------------------


class TestTheOperatorAuditFamilyHasTwoMembers:
    def test_the_literal_carries_both_and_neither_is_task_scoped(self) -> None:
        """T6 added the first member; this adds the second to the same Literal.

        The point of one Literal rather than two is that a single audit read
        finds both families of process-level operator action. The point of it
        being *shared* is that T6's structural binding (a test asserting the
        written payload value is a member) now covers this value too.
        """

        assert set(get_args(OperatorAuditActionType)) == {"activate_version", "raw_payload_read"}
        assert RAW_PAYLOAD_READ_ACTION in get_args(OperatorAuditActionType)
        # The Task-scoped family is untouched: those own a ledger row keyed by
        # a Task and `OperatorActionView.task_id` is required.
        assert set(get_args(TaskOperatorActionType)) == {"interrupt", "rollback"}
        assert RAW_PAYLOAD_READ_ACTION not in get_args(TaskOperatorActionType)


class TestTheScopeSubjectArm:
    """RC8's validator arm, and the garbage it must keep refusing."""

    def _envelope(self, **overrides: Any) -> ObservationEnvelope:
        base: dict[str, Any] = {
            "status": "requested",
            "read_id": new_id(),
            "actor": str(_ADMIN_ID),
            "target_kind": "content_block",
            "target_id": new_id(),
            "occurred_at": _OCCURRED_AT,
            "task_id": ANSICH_BOOTSTRAP_TASK_ID,
            "subject_type": "scope",
            "subject_id": host_scope_id("some-host"),
        }
        base.update(overrides)
        return ObservationEnvelope.raw_payload_read(**base)

    def test_a_scope_subject_is_admitted_for_a_process_scoped_action(self) -> None:
        observation = self._envelope()

        assert observation.kind == "operator.action_requested"
        assert observation.subject_type == "scope"
        assert observation.task_id == ANSICH_BOOTSTRAP_TASK_ID

    def test_a_task_subject_is_still_admitted_for_the_owning_task(self) -> None:
        """The arm widens the rule; it does not replace it."""

        task_id = new_id()
        observation = self._envelope(task_id=task_id, subject_type="task", subject_id=task_id)

        assert observation.subject_type == "task"
        assert observation.subject_id == task_id

    def test_a_scope_subject_beside_a_real_task_is_refused(self) -> None:
        """A row claiming both a Scope and a Task is about neither, readably."""

        with pytest.raises(ValidationError, match="bootstrap Task sentinel"):
            self._envelope(task_id=new_id())

    def test_a_task_scoped_action_may_not_subject_a_scope(self) -> None:
        """`interrupt`/`rollback` own a ledger row keyed by a Task."""

        with pytest.raises(ValidationError, match="process-scoped operator action"):
            ObservationEnvelope(
                kind="operator.action_requested",
                occurred_at=_OCCURRED_AT,
                task_id=ANSICH_BOOTSTRAP_TASK_ID,
                subject_type="scope",
                subject_id=host_scope_id("some-host"),
                producer=Producer(name="p", version="1", instance_id="i"),
                source_event_id="garbage",
                correlation_id=new_id(),
                payload={"action_type": "interrupt"},
            )

    def test_a_mismatched_task_subject_is_still_refused(self) -> None:
        """The pre-existing arm, unchanged: subject_id must be the task_id."""

        with pytest.raises(ValidationError, match="must identify task_id"):
            ObservationEnvelope(
                kind="operator.action_requested",
                occurred_at=_OCCURRED_AT,
                task_id=new_id(),
                subject_type="task",
                subject_id=new_id(),
                producer=Producer(name="p", version="1", instance_id="i"),
                source_event_id="garbage",
                correlation_id=new_id(),
                payload={"action_type": "raw_payload_read"},
            )


# ---------------------------------------------------------------------------
# The audited happy path
# ---------------------------------------------------------------------------


class TestAnAuditedReadWritesTwoRowsAndNoBody:
    @pytest.mark.anyio
    async def test_a_served_read_records_actor_target_purpose_correlation_and_time(self, tmp_path: Path) -> None:
        async with _harness(tmp_path) as harness:
            task_id, block_id = await _planted_block(harness, body={"content": "sensitive-marker"})

            response = await harness.client.get(
                f"/api/ansich/content-blocks/{block_id}/payload",
                params={"purpose": "incident 4711"},
                headers={"X-Trace-Id": "trace-abc"},
            )

            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            payloads = await harness.audit_payloads()

        assert [payload["status"] for payload in payloads] == ["requested", "succeeded"]
        requested, succeeded = payloads
        # spec:112's list, all five of it.
        assert requested["actor"] == str(_ADMIN_ID)
        assert requested["target_kind"] == "content_block"
        assert requested["target_id"] == block_id
        assert requested["purpose"] == "incident 4711"
        assert requested["request_correlation_id"] == "trace-abc"
        # One read, one id: the pair is joinable and nothing else shares it.
        assert requested["read_id"] == succeeded["read_id"]
        assert succeeded["outcome"] == "served"
        assert succeeded["http_status"] == 200
        assert succeeded["served_byte_size"] > 0
        # …and never the body. Not in either row, at any depth.
        assert "sensitive-marker" not in str(payloads)
        assert task_id  # planted for the subject assertion below

    @pytest.mark.anyio
    async def test_the_subject_is_the_owning_task_when_the_payload_has_one(self, tmp_path: Path) -> None:
        """RC8's first arm. The Task is resolved from the block's Observation."""

        async with _harness(tmp_path) as harness:
            task_id, block_id = await _planted_block(harness)

            await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            rows = await harness.audit_rows()

        assert [row.subject_type for row in rows] == ["task", "task"]
        assert {row.subject_id for row in rows} == {task_id}
        assert {row.task_id for row in rows} == {task_id}

    @pytest.mark.anyio
    async def test_the_subject_is_the_host_scope_when_nothing_owns_the_payload(self, tmp_path: Path) -> None:
        """RC8's second arm, on the one route whose target is never Task-scoped.

        A release manifest is the identity of a build, so there is no owning
        Task to subject — and the service minted a host ``Scope`` at start, so
        the honest subject is that Scope rather than the sentinel.
        """

        async with _harness(tmp_path) as harness:
            response = await harness.client.get(f"/api/ansich/agent-releases/{new_id()}/manifest")
            rows = await harness.audit_rows()

        assert response.status_code == 404
        assert [row.subject_type for row in rows] == ["scope", "scope"]
        assert {row.subject_id for row in rows} == {host_scope_id(harness.service._hostname)}
        # The Task field stays the sentinel, which is what keeps the assessor
        # family away from these rows.
        assert {row.task_id for row in rows} == {ANSICH_BOOTSTRAP_TASK_ID}

    @pytest.mark.anyio
    async def test_a_second_read_of_the_same_payload_by_the_same_actor_is_a_second_audit(self, tmp_path: Path) -> None:
        """H7-D. A deterministic ``(actor, payload)`` key would dedupe this away.

        The producer dedupe is keyed on
        ``(producer, instance_id, source_event_id)`` and silently absorbs a
        repeat, so a key built from who-read-what would make the *second* read —
        the one an auditor most wants — invisible.
        """

        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)

            first = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            second = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            payloads = await harness.audit_payloads()

        assert first.status_code == 200
        assert second.status_code == 200
        assert len(payloads) == 4
        assert len({payload["read_id"] for payload in payloads}) == 2

    @pytest.mark.anyio
    async def test_every_raw_route_audits(self, tmp_path: Path) -> None:
        """All four, so none can be added to the family and forgotten."""

        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)
            await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            await harness.client.get(f"/api/ansich/agent-releases/{new_id()}/manifest")
            await harness.client.get(f"/api/ansich/evaluations/{new_id()}/payload")
            await harness.client.get(f"/api/ansich/tool-calls/{new_id()}/raw-result")
            await harness.client.get(f"/api/ansich/tool-calls/{new_id()}/visible-result")
            payloads = await harness.audit_payloads()

        assert [payload["target_kind"] for payload in payloads if payload["status"] == "requested"] == [
            "content_block",
            "agent_release",
            "evaluation",
            "tool_call",
            "tool_call",
        ]

    @pytest.mark.anyio
    async def test_the_audit_rows_mint_no_projection_work(self, tmp_path: Path) -> None:
        """Global Constraint 4: nothing below any continuity mark.

        ``operator.action_*`` is in no projector's kind list, so the rows are
        evidence and nothing else. If that ever changed, an audited read would
        start enqueueing jobs on the ingest path from an admin GET.
        """

        from deerflow.ansich.persistence.models import AnsichProjectionJobRow

        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)
            before = await harness.service.rebuild_until_settled()
            await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            async with harness.session_factory() as session:
                jobs = [row.obs_id for row in (await session.execute(select(AnsichProjectionJobRow))).scalars()]
                audit_ids = {row.obs_id for row in await harness.audit_rows()}

        assert before.unsettled == 0
        assert audit_ids
        assert not (audit_ids & set(jobs))


# ---------------------------------------------------------------------------
# Denial: audited, and the payload is never read
# ---------------------------------------------------------------------------


class TestADeniedReadIsAuditedWithoutReading:
    @pytest.mark.anyio
    async def test_a_non_admin_is_audited_and_the_read_path_is_never_entered(self, tmp_path: Path) -> None:
        probe = _ReadProbe()
        async with _harness(tmp_path, user_factory=_regular_user) as harness:
            probe.wrap(harness.service, "get_content_block_payload")

            response = await harness.client.get(f"/api/ansich/content-blocks/{new_id()}/payload")
            payloads = await harness.audit_payloads()

        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
        # Instrumented, not inferred: nothing asked the store for a body.
        assert probe.calls == 0
        # One row, not a pair: there was no attempt to terminalize.
        assert [payload["status"] for payload in payloads] == ["failed"]
        assert payloads[0]["outcome"] == "denied_not_admin"
        assert payloads[0]["http_status"] == 403
        assert payloads[0]["actor"] == str(_REGULAR_ID)

    @pytest.mark.anyio
    async def test_every_raw_route_audits_its_denial(self, tmp_path: Path) -> None:
        async with _harness(tmp_path, user_factory=_regular_user) as harness:
            await harness.client.get(f"/api/ansich/content-blocks/{new_id()}/payload")
            await harness.client.get(f"/api/ansich/agent-releases/{new_id()}/manifest")
            await harness.client.get(f"/api/ansich/evaluations/{new_id()}/payload")
            await harness.client.get(f"/api/ansich/tool-calls/{new_id()}/raw-result")
            await harness.client.get(f"/api/ansich/tool-calls/{new_id()}/visible-result")
            payloads = await harness.audit_payloads()

        assert [payload["outcome"] for payload in payloads] == ["denied_not_admin"] * 5

    @pytest.mark.anyio
    async def test_a_disabled_service_refuses_without_auditing_and_still_says_no_store(self, tmp_path: Path) -> None:
        """The refusals that precede the audit are still answers from this family.

        There is nothing to record — no service to record it with, and no body
        fetched — but ``no-store`` is a property of the *route*, not of whether
        it managed to reach the store, and the rule is worth being able to
        state without an exception.
        """

        async with _harness(tmp_path) as harness:
            harness.app.state.ansich_service = None

            response = await harness.client.get(f"/api/ansich/content-blocks/{new_id()}/payload")

        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# The inversion itself
# ---------------------------------------------------------------------------


class TestAnUnpersistableAuditRefusesTheRead:
    @staticmethod
    def _break_the_audit(harness: _RawReadHarness) -> None:
        async def _fails(**_kwargs: Any) -> str:
            raise RuntimeError("audit storage is down")

        harness.service._backend.record_raw_read_audit = _fails  # type: ignore[attr-defined]

    @pytest.mark.anyio
    async def test_a_failed_requested_audit_answers_503_and_reads_nothing(self, tmp_path: Path) -> None:
        """§7's inversion, both halves.

        The 503 is the visible half; ``probe.calls == 0`` is the half that
        matters. A fail-open version of this route would answer 200 here and
        the response alone could not tell the two apart.
        """

        probe = _ReadProbe()
        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)
            probe.wrap(harness.service, "get_content_block_payload")
            self._break_the_audit(harness)

            response = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")

        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert "audit" in response.json()["detail"]["message"]
        assert probe.calls == 0

    @pytest.mark.anyio
    async def test_all_four_routes_refuse(self, tmp_path: Path) -> None:
        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)
            self._break_the_audit(harness)

            statuses = [
                (await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")).status_code,
                (await harness.client.get(f"/api/ansich/agent-releases/{new_id()}/manifest")).status_code,
                (await harness.client.get(f"/api/ansich/evaluations/{new_id()}/payload")).status_code,
                (await harness.client.get(f"/api/ansich/tool-calls/{new_id()}/raw-result")).status_code,
                (await harness.client.get(f"/api/ansich/tool-calls/{new_id()}/visible-result")).status_code,
            ]

        assert statuses == [503] * 5

    @pytest.mark.anyio
    async def test_metadata_and_inventory_routes_stay_readable_through_the_same_failure(self, tmp_path: Path) -> None:
        """spec:114's second sentence, and the reason the inversion is bounded.

        The audit gates *bodies*. A store whose audit writer is broken still
        answers every metadata read, so an operator diagnosing the outage keeps
        the whole observability surface except the four raw routes.
        """

        async with _harness(tmp_path) as harness:
            task_id, block_id = await _planted_block(harness)
            self._break_the_audit(harness)

            raw = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            task = await harness.client.get(f"/api/ansich/tasks/{task_id}")
            steps = await harness.client.get(f"/api/ansich/tasks/{task_id}/steps")
            timeline = await harness.client.get(f"/api/ansich/tasks/{task_id}/timeline")
            lineage = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/lineage")
            listing = await harness.client.get("/api/ansich/tasks")
            health = await harness.client.get("/api/ansich/health")

        assert raw.status_code == 503
        assert [response.status_code for response in (task, steps, timeline, lineage, listing, health)] == [200] * 6

    @pytest.mark.anyio
    async def test_a_backend_that_cannot_audit_at_all_refuses_the_same_way(self, tmp_path: Path) -> None:
        """ "No audit writer" and "the writer failed" are one statement here.

        A service whose backend cannot record the access must not serve it
        either — otherwise the control is one missing method away from silently
        not existing.
        """

        class _BackendWithoutAnAuditWriter:
            async def persist_and_project(self, observations: list[ObservationEnvelope]) -> int:
                return len(observations)

        service = AnsichService.in_memory()
        service._backend = _BackendWithoutAnAuditWriter()  # type: ignore[assignment]
        with pytest.raises(RawReadAuditUnavailableError):
            await service.audit_raw_payload_read(
                status="requested",
                read_id=new_id(),
                actor="someone",
                target_kind="content_block",
                target_id=new_id(),
            )


# ---------------------------------------------------------------------------
# Outcomes other than "served"
# ---------------------------------------------------------------------------


class TestEveryOutcomeIsAudited:
    @pytest.mark.anyio
    async def test_a_missing_payload_is_audited_as_not_found_with_no_store(self, tmp_path: Path) -> None:
        async with _harness(tmp_path) as harness:
            response = await harness.client.get(f"/api/ansich/content-blocks/{new_id()}/payload")
            payloads = await harness.audit_payloads()

        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
        assert payloads[1]["outcome"] == "not_found"
        assert payloads[1]["http_status"] == 404

    @pytest.mark.anyio
    async def test_an_expired_payload_is_audited_as_a_read_that_was_answered(self, tmp_path: Path) -> None:
        """T9a's 410, given an audit vocabulary.

        The read **was** attempted and the store answered it, so this is not a
        denial — but nothing was disclosed, so it is not ``succeeded`` either.
        ``failed`` + ``outcome="expired"`` is the pair that keeps
        "who obtained bytes" answerable by looking at one field: only a
        ``succeeded`` row means a body crossed the wire.
        """

        async with _harness(tmp_path) as harness:
            block_id = new_id()

            async def _expired(_block_id: str):
                raise PayloadExpiredError(
                    "expired",
                    payload_id="payload-expired",
                    policy="raw_payload_days=7",
                    deleted_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
                    sha256="a" * 64,
                    byte_size=4096,
                )

            harness.service.get_content_block_payload = _expired  # type: ignore[method-assign]
            response = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            payloads = await harness.audit_payloads()

        assert response.status_code == 410
        assert response.headers["cache-control"] == "no-store"
        assert payloads[1]["status"] == "failed"
        assert payloads[1]["outcome"] == "expired"
        assert payloads[1]["http_status"] == 410
        assert "served_byte_size" not in payloads[1]

    @pytest.mark.anyio
    async def test_a_failing_store_is_audited_as_read_failed(self, tmp_path: Path) -> None:
        async with _harness(tmp_path) as harness:

            async def _boom(_block_id: str):
                raise RuntimeError("storage is down")

            harness.service.get_content_block_payload = _boom  # type: ignore[method-assign]
            response = await harness.client.get(f"/api/ansich/content-blocks/{new_id()}/payload")
            payloads = await harness.audit_payloads()

        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert payloads[1]["outcome"] == "read_failed"

    @pytest.mark.anyio
    async def test_an_oversized_body_is_refused_and_the_refusal_is_audited(self, tmp_path: Path) -> None:
        """The v1 size limit (spec:118). A refusal is an outcome, not a silence."""

        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness, body={"content": "x" * 4096})
            harness.set_raw_read_settings(AnsichConfig(raw_read_max_bytes=64))

            response = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            payloads = await harness.audit_payloads()

        assert response.status_code == 413
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["detail"]["limit_bytes"] == 64
        assert response.json()["detail"]["byte_size"] > 64
        assert payloads[1]["status"] == "failed"
        assert payloads[1]["outcome"] == "oversize"
        # Nothing was served, so there is no served size to record.
        assert "served_byte_size" not in payloads[1]

    @pytest.mark.anyio
    async def test_the_limit_default_is_one_mebibyte_and_is_startup_only(self) -> None:
        assert AnsichConfig().raw_read_max_bytes == 1_048_576
        assert snapshot_ansich_raw_read_settings(None).max_bytes == 1_048_576
        assert "startup-only" in (AnsichConfig.model_fields["raw_read_max_bytes"].description or "")

    @pytest.mark.anyio
    async def test_an_over_long_purpose_is_refused_before_anything_is_read(self, tmp_path: Path) -> None:
        """Bounded by the route's own validation, which runs before the handler."""

        probe = _ReadProbe()
        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)
            probe.wrap(harness.service, "get_content_block_payload")

            response = await harness.client.get(
                f"/api/ansich/content-blocks/{block_id}/payload",
                params={"purpose": "p" * (ansich_router.RAW_READ_PURPOSE_MAX_LENGTH + 1)},
            )

        assert response.status_code == 422
        assert probe.calls == 0


class TestTheResponseHeaders:
    @pytest.mark.anyio
    async def test_a_non_json_body_is_served_as_an_attachment(self, tmp_path: Path) -> None:
        """The artifacts router's rule, one layer in.

        The declared content type came out of a tool result, so it is data
        rather than a promise; forcing the download costs nothing and keeps
        active content from ever being rendered by a viewer that unwraps it.
        """

        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness, body="<script>alert(1)</script>")

            async def _html(block: str):
                payload = await AnsichService.get_content_block_payload(harness.service, block)
                return payload.model_copy(update={"content_type": "text/html"})

            harness.service.get_content_block_payload = _html  # type: ignore[method-assign]
            response = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-disposition"].startswith("attachment;")

    @pytest.mark.anyio
    async def test_a_json_body_is_not_an_attachment(self, tmp_path: Path) -> None:
        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)

            response = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")

        assert response.status_code == 200
        assert "content-disposition" not in response.headers


class TestTheAuditWriterItself:
    @pytest.mark.anyio
    async def test_the_outcome_row_degrades_rather_than_failing_a_served_read(self, tmp_path: Path) -> None:
        """The deliberate asymmetry between the two rows.

        By the time the terminal row is written the body has been read and the
        *access* is durably on record. Refusing the response then would report
        a read that happened as an error while disclosing it anyway.
        """

        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)
            original = harness.service._backend.record_raw_read_audit  # type: ignore[attr-defined]

            async def _only_the_first(**kwargs: Any) -> str:
                if kwargs["status"] != "requested":
                    raise RuntimeError("audit storage went down mid-read")
                return await original(**kwargs)

            harness.service._backend.record_raw_read_audit = _only_the_first  # type: ignore[attr-defined]
            response = await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            payloads = await harness.audit_payloads()

        assert response.status_code == 200
        assert [payload["status"] for payload in payloads] == ["requested"]

    @pytest.mark.anyio
    async def test_an_unknown_target_kind_is_refused_rather_than_written(self, tmp_path: Path) -> None:
        async with _harness(tmp_path) as harness:
            with pytest.raises(RawReadAuditUnavailableError):
                await harness.service.audit_raw_payload_read(
                    status="requested",
                    read_id=new_id(),
                    actor="someone",
                    target_kind="not_a_thing",
                    target_id=new_id(),
                )

    @pytest.mark.anyio
    async def test_two_rows_of_one_read_are_distinct_source_events(self, tmp_path: Path) -> None:
        """Otherwise the producer dedupe would absorb the terminal row."""

        async with _harness(tmp_path) as harness:
            _task_id, block_id = await _planted_block(harness)
            await harness.client.get(f"/api/ansich/content-blocks/{block_id}/payload")
            rows = await harness.audit_rows()

        assert len({row.source_event_id for row in rows}) == 2
        assert all(row.producer_name == "ansich-raw-read-audit" for row in rows)
