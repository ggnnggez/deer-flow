from datetime import UTC, datetime
from uuid import uuid4

import pytest
from ansich.contracts import ObservationEnvelope, Producer
from ansich.safety import scope_entity_id, scope_reference_hash


def _scope_id() -> str:
    return scope_entity_id("sandbox", scope_reference_hash("sandbox", "local:thread-1"))


def _payload(**overrides) -> dict:
    base = {
        "environment_scope": "container",
        "coverage": "continuous",
        "window": {
            "started_at": datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
            "ended_at": datetime(2026, 8, 19, 12, 0, 10, tzinfo=UTC),
            "sample_count": 1,
        },
        "provider": "aio",
        "metrics": {"fd_open": {"value": 120, "limit": 1024}},
        "tool_call_id": None,
    }
    base.update(overrides)
    return base


def _envelope(payload: dict) -> ObservationEnvelope:
    return ObservationEnvelope.environment_sampled(
        task_id=str(uuid4()),
        run_id="run-1",
        occurred_at=datetime(2026, 8, 19, 12, 0, 10, tzinfo=UTC),
        scope_id=_scope_id(),
        payload=payload,
        source_event_id="run:run-1:env:s:1",
    )


def test_environment_sampled_builder_produces_scope_subject():
    envelope = _envelope(_payload())
    assert envelope.kind == "environment.sampled"
    assert envelope.subject_type == "scope"
    assert envelope.subject_id == _scope_id()


def test_environment_sampled_rejects_missing_marks():
    payload = _payload()
    del payload["environment_scope"]
    with pytest.raises(ValueError):
        _envelope(payload)


def test_uninstrumented_requires_empty_metrics_and_zero_samples():
    with pytest.raises(ValueError):
        _envelope(_payload(coverage="uninstrumented"))
    payload = _payload(coverage="uninstrumented", metrics={})
    payload["window"]["sample_count"] = 0
    assert _envelope(payload).payload["coverage"] == "uninstrumented"


def test_per_command_requires_tool_call_id_and_process_group():
    with pytest.raises(ValueError):
        _envelope(_payload(coverage="per_command", environment_scope="process_group"))
    ok = _payload(
        coverage="per_command",
        environment_scope="process_group",
        tool_call_id=str(uuid4()),
    )
    assert _envelope(ok).payload["tool_call_id"] is not None
    with pytest.raises(ValueError):
        _envelope(_payload(tool_call_id=str(uuid4())))  # continuous 不许携带


def test_metrics_never_write_zero_for_missing_dimension():
    payload = _payload(metrics={"io_read_bytes": {"value": 5}})
    envelope = _envelope(payload)
    assert "fd_open" not in envelope.payload["metrics"]


def test_instrumented_sample_requires_metrics():
    with pytest.raises(ValueError):
        _envelope(_payload(metrics={}))


def _stored_envelope(*, payload: dict | None, payload_ref_id: str | None) -> ObservationEnvelope:
    """An envelope in the shape ``_observation_from_row`` builds from a row.

    Not the ``environment_sampled`` builder: that one is the *write* side and
    always carries an inline payload. A stored row that went over
    ``inline_payload_max_bytes`` reads back as ``payload_json IS NULL`` plus a
    ``payload_ref_id``, and this is the only way to reproduce that shape.
    """

    return ObservationEnvelope(
        kind="environment.sampled",
        occurred_at=datetime(2026, 8, 19, 12, 0, 10, tzinfo=UTC),
        task_id=str(uuid4()),
        subject_type="scope",
        subject_id=_scope_id(),
        producer=Producer(name="environment-probe", version="1", instance_id="local"),
        source_event_id="run:run-1:env:s:1",
        correlation_id="run-1",
        payload=payload,
        payload_ref_id=payload_ref_id,
    )


def test_externalized_environment_sample_validates_on_read_back():
    """F10-29 ①: an externalized sample must survive every public read.

    A payload over ``inline_payload_max_bytes`` is stored in
    ``ansich_payloads``; the Observation row keeps ``payload_json IS NULL`` and
    a ``payload_ref_id``, and ``_observation_from_row`` hands exactly that pair
    to this model. Until this branch was guarded it raised unconditionally on
    the ``None``, so ``list_observations`` / ``list_timeline`` / alert-evidence
    reads of the owning Task all blew up on an environment sample that was
    merely large.
    """

    envelope = _stored_envelope(payload=None, payload_ref_id=str(uuid4()))

    assert envelope.payload is None
    assert envelope.payload_ref_id is not None


def test_a_sample_with_neither_a_payload_nor_a_ref_is_still_rejected():
    """The guard skips validation on ``None``; it does not drop the rule.

    An environment sample carrying neither an inline payload nor a
    ``payload_ref_id`` is payload-less — nothing externalized it, so there is
    nothing to hydrate — and it is still refused. That rule now lives where it
    holds for every kind (the envelope's exactly-one-of check) rather than in
    this one branch, which is what let the branch guard; this pins that the
    replacement really does cover it.
    """

    with pytest.raises(ValueError, match="exactly one of payload and payload_ref_id"):
        _stored_envelope(payload=None, payload_ref_id=None)


def test_host_scope_kind_and_role_exist():
    from ansich.safety import ScopeDescriptor

    host_id = scope_entity_id("host", scope_reference_hash("host", "my-host"))
    descriptor = ScopeDescriptor(
        scope_id=host_id,
        scope_kind="host",
        external_ref_hash=scope_reference_hash("host", "my-host"),
        display_label="host:my-host",
        created_obs_id=str(uuid4()),
    )
    assert descriptor.scope_kind == "host"


def test_scope_snapshotted_builder():
    from ansich.safety import scope_display_label

    ref_hash = scope_reference_hash("sandbox", "local:thread-1")
    obs = ObservationEnvelope.scope_snapshotted(
        task_id=str(uuid4()),
        run_id="run-1",
        occurred_at=datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC),
        scope_kind="sandbox",
        external_ref="local:thread-1",
        relation_role="sandbox_boundary",
        source_event_id="run:run-1:env-scope:sandbox",
    )
    assert obs.kind == "scope.snapshotted"
    assert obs.subject_id == scope_entity_id("sandbox", ref_hash)
    assert obs.payload["relation_role"] == "sandbox_boundary"
    assert obs.payload["scope"]["display_label"] == scope_display_label("sandbox", "local:thread-1")
