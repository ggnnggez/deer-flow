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
