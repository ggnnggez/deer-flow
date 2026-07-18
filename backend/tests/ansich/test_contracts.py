from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ansich import ObservationEnvelope, Producer, new_id
from pydantic import ValidationError


def test_observation_contract_rejects_naive_time_and_non_uuid_identity() -> None:
    with pytest.raises(ValidationError):
        ObservationEnvelope.task_lifecycle(
            kind="task.created",
            task_id="provider-run-id",
            source_kind="deerflow_run",
            source_id="run-1",
            occurred_at=datetime(2026, 7, 17, 8, 0),
            source_event_id="run:run-1:task:created",
        )


def test_observation_contract_rejects_secret_bearing_payload_fields() -> None:
    task_id = new_id()

    with pytest.raises(ValidationError, match="secret-bearing field"):
        ObservationEnvelope(
            kind="task.created",
            occurred_at=datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
            task_id=task_id,
            subject_id=task_id,
            producer=Producer(name="test", version="1", instance_id="local"),
            source_event_id="run:run-1:task:created",
            correlation_id="run-1",
            payload={
                "source_kind": "deerflow_run",
                "source_id": "run-1",
                "request": {"Authorization": "Bearer should-never-persist"},
            },
        )


def test_ansich_core_has_no_deerflow_or_web_framework_imports() -> None:
    package_root = Path(__file__).parents[2] / "packages" / "ansich" / "ansich"
    forbidden_roots = {"app", "deerflow", "fastapi", "langgraph"}
    violations: list[str] = []

    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for module in imported:
                if module.split(".", maxsplit=1)[0] in forbidden_roots:
                    violations.append(f"{path.relative_to(package_root)} imports {module}")

    assert violations == []


def test_phase_two_observation_accepts_step_subject_with_explicit_parent() -> None:
    task_id = new_id()
    step_id = new_id()

    observation = ObservationEnvelope(
        kind="step.started",
        occurred_at=datetime.now(UTC),
        task_id=task_id,
        step_id=step_id,
        subject_type="step",
        subject_id=step_id,
        producer=Producer(name="decision-probe", version="1", instance_id="worker-1"),
        producer_seq=1,
        source_event_id=f"step:{step_id}:started",
        correlation_id=task_id,
        payload={"step_seq": 1, "actor_kind": "lead_agent"},
    )

    assert observation.step_id == step_id
    assert observation.subject_id == step_id


def test_phase_five_observation_builders_reject_invalid_measurements() -> None:
    task_id = new_id()
    now = datetime.now(UTC)

    with pytest.raises(ValidationError, match="elapsed_ms"):
        ObservationEnvelope.task_heartbeat(
            task_id=task_id,
            run_id="run-invalid-heartbeat",
            occurred_at=now,
            elapsed_ms=-1,
            worker_id="worker-a",
            ownership_epoch="worker-a",
            source_event_id="run:run-invalid-heartbeat:heartbeat:1",
        )

    with pytest.raises(ValidationError, match="effective_value"):
        ObservationEnvelope.budget_configured(
            task_id=task_id,
            run_id="run-invalid-budget",
            occurred_at=now,
            dimension="steps",
            aggregation_scope="local",
            warning_limit=None,
            hard_limit=None,
            enforcement=False,
            source_kind="shadow",
            requested_value=None,
            effective_value=-1,
            source_event_id="run:run-invalid-budget:budget:steps",
        )


def test_phase_six_operator_observations_use_alert_and_task_subjects() -> None:
    task_id = new_id()
    alert_id = new_id()
    producer = Producer(
        name="operator-api",
        version="1",
        instance_id="gateway-test",
    )
    now = datetime.now(UTC)

    alert_observation = ObservationEnvelope(
        kind="operator.alert_acknowledged",
        occurred_at=now,
        task_id=task_id,
        subject_type="alert",
        subject_id=alert_id,
        producer=producer,
        source_event_id=f"alert:{alert_id}:acknowledged:2",
        correlation_id="request-ack-1",
        payload={"workflow_version": 2},
    )
    action_observation = ObservationEnvelope(
        kind="operator.action_requested",
        occurred_at=now,
        task_id=task_id,
        subject_type="task",
        subject_id=task_id,
        producer=producer,
        source_event_id="task:action:interrupt:request-1:requested",
        correlation_id="request-1",
        payload={"action": "interrupt", "idempotency_key": "request-1"},
    )

    assert alert_observation.subject_id == alert_id
    assert action_observation.subject_id == task_id


def test_phase_six_operator_observation_rejects_the_wrong_subject_type() -> None:
    task_id = new_id()

    with pytest.raises(ValidationError, match="Alert workflow observation"):
        ObservationEnvelope(
            kind="operator.alert_dismissed",
            occurred_at=datetime.now(UTC),
            task_id=task_id,
            subject_type="task",
            subject_id=task_id,
            producer=Producer(
                name="operator-api",
                version="1",
                instance_id="gateway-test",
            ),
            source_event_id="alert:dismissed:wrong-subject",
            correlation_id="request-dismiss-1",
            payload={"workflow_version": 2, "reason": "false_positive"},
        )
