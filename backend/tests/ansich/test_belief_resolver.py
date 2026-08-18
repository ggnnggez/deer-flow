from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ansich import AnsichService, ObservationEnvelope, new_id
from ansich.assessment.base import Assessment, EvidenceRef, canonical_config_hash
from ansich.belief.resolver import (
    DEFAULT_RESOLVER,
    RESOLVER_V1,
    BeliefAssertion,
    resolve_current_belief,
)
from ansich.contracts import NamedVersion
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.ansich.persistence.models import (
    AnsichBeliefAssertionRow,
    AnsichCurrentBeliefRow,
)
from deerflow.ansich.persistence.sql import SqlAnsichBackend
from deerflow.persistence.base import Base

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
V2_AUTHORITY_ORDER = (
    "human_override",
    "deterministic",
    "configured_rule",
    "soft_human",
    "automated",
)


def _assessment(
    *,
    subject_id: str = "task-1",
    field_name: str = "quality",
    value: str,
    as_of: datetime,
    authority_class: str,
    fidelity_class: str = "soft",
) -> Assessment:
    return Assessment(
        subject_id=subject_id,
        field_name=field_name,
        value={"value": value},
        as_of=as_of,
        asserted_at=as_of,
        assessor={"name": f"{authority_class}-source", "version": "1.0.0"},
        config_hash=canonical_config_hash({"source": authority_class}),
        authority_class=authority_class,
        fidelity_class=fidelity_class,
        evidence=(EvidenceRef(obs_id=f"obs-{authority_class}"),),
    )


def _assertion(
    assertion_id: str,
    *,
    value: str = "on_track",
    as_of: datetime = NOW,
    authority_class: str,
    fidelity_class: str = "soft",
) -> BeliefAssertion:
    return BeliefAssertion.from_assessment(
        _assessment(
            value=value,
            as_of=as_of,
            authority_class=authority_class,
            fidelity_class=fidelity_class,
        ),
        assertion_id=assertion_id,
    )


def _selection_order(
    assertions: tuple[BeliefAssertion, ...],
    *,
    resolver: NamedVersion = DEFAULT_RESOLVER,
) -> list[str]:
    remaining = list(assertions)
    order: list[str] = []
    while remaining:
        resolved = resolve_current_belief(tuple(remaining), resolver=resolver)
        order.append(resolved.selected.authority_class)
        remaining = [item for item in remaining if item.assertion_id != resolved.selected.assertion_id]
    return order


def test_default_resolver_is_ansich_default_v2_and_v1_is_retained() -> None:
    assert DEFAULT_RESOLVER == NamedVersion(name="ansich-default", version="2.0.0")
    assert RESOLVER_V1 == NamedVersion(name="ansich-default", version="1.0.0")


def test_v2_ranks_all_five_authority_classes_above_recency() -> None:
    # The lowest authority carries the newest as_of, so a selection that follows
    # the authority order proves authority dominates recency.
    assertions = tuple(
        _assertion(
            f"assertion-{authority_class}",
            authority_class=authority_class,
            as_of=NOW + timedelta(hours=index),
        )
        for index, authority_class in enumerate(V2_AUTHORITY_ORDER)
    )

    assert _selection_order(assertions) == list(V2_AUTHORITY_ORDER)


def test_v2_records_the_resolver_that_produced_the_selection() -> None:
    resolved = resolve_current_belief((_assertion("assertion-a", authority_class="soft_human"),))

    assert resolved.resolver == DEFAULT_RESOLVER
    assert resolved.resolver.version == "2.0.0"


def test_v2_tie_break_prefers_newer_as_of_over_later_asserted_at() -> None:
    newest_evidence = _assertion(
        "assertion-newest-evidence",
        authority_class="soft_human",
        as_of=NOW,
    )
    late_commit_of_older_evidence = _assertion(
        "assertion-late-commit",
        authority_class="soft_human",
        as_of=NOW - timedelta(hours=1),
    ).model_copy(update={"asserted_at": NOW + timedelta(hours=1)})

    resolved = resolve_current_belief((late_commit_of_older_evidence, newest_evidence))

    assert resolved.selected.assertion_id == "assertion-newest-evidence"


def test_v2_tie_break_uses_asserted_at_then_assertion_id() -> None:
    earlier_commit = _assertion("assertion-z", authority_class="soft_human")
    later_commit = earlier_commit.model_copy(
        update={
            "assertion_id": "assertion-a",
            "asserted_at": NOW + timedelta(minutes=1),
        },
    )
    same_commit_higher_id = earlier_commit.model_copy(update={"assertion_id": "assertion-zz"})

    assert resolve_current_belief((earlier_commit, later_commit)).selected.assertion_id == "assertion-a"
    assert resolve_current_belief((earlier_commit, same_commit_higher_id)).selected.assertion_id == "assertion-zz"


def test_conflicting_assertion_count_counts_retained_non_selected_assertions() -> None:
    assertions = tuple(_assertion(f"assertion-{index}", authority_class="automated", as_of=NOW + timedelta(minutes=index)) for index in range(4))

    assert resolve_current_belief(assertions).conflicting_assertion_count == 3
    assert resolve_current_belief(assertions[:1]).conflicting_assertion_count == 0


def test_resolver_v1_reproduces_the_legacy_priority_table() -> None:
    legacy_order = ("human_override", "deterministic", "configured_rule", "automated")
    assertions = tuple(
        _assertion(
            f"assertion-{authority_class}",
            authority_class=authority_class,
            as_of=NOW + timedelta(hours=index),
        )
        for index, authority_class in enumerate(legacy_order)
    )

    resolved = resolve_current_belief(assertions, resolver=RESOLVER_V1)

    assert _selection_order(assertions, resolver=RESOLVER_V1) == list(legacy_order)
    assert resolved.resolver == RESOLVER_V1
    assert resolved.resolver.version == "1.0.0"


def test_resolver_v1_rejects_soft_human_assertions() -> None:
    assertions = (
        _assertion("assertion-automated", authority_class="automated"),
        _assertion("assertion-soft-human", authority_class="soft_human"),
    )

    with pytest.raises(ValueError, match="authority class soft_human is not resolvable under ansich-default@1.0.0"):
        resolve_current_belief(assertions, resolver=RESOLVER_V1)


def test_unknown_resolver_version_is_rejected() -> None:
    assertions = (_assertion("assertion-automated", authority_class="automated"),)

    with pytest.raises(ValueError, match="unsupported belief resolver ansich-default@3.0.0"):
        resolve_current_belief(assertions, resolver=NamedVersion(name="ansich-default", version="3.0.0"))


@pytest.mark.anyio
async def test_sql_current_belief_records_v2_and_selects_soft_human_over_automated(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ansich-resolver-v2.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    backend = SqlAnsichBackend(session_factory)
    service = AnsichService(backend, terminal_flush_timeout_ms=10_000)
    await service.start()
    task_id = new_id()
    observed_at = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)

    try:
        service.record(
            ObservationEnvelope.task_lifecycle(
                kind="task.created",
                task_id=task_id,
                source_kind="deerflow_run",
                source_id="run-resolver-v2",
                occurred_at=observed_at,
                source_event_id="run:run-resolver-v2:task:created",
            )
        )
        await service.flush_task(task_id)
        async with session_factory() as session:
            # The automated assertion carries the newer evidence time, so a
            # soft_human selection can only come from the v2 authority table.
            await backend._persist_assessment(
                session,
                _assessment(
                    subject_id=task_id,
                    value="on_track",
                    as_of=observed_at + timedelta(minutes=5),
                    authority_class="automated",
                ),
            )
            await backend._persist_assessment(
                session,
                _assessment(
                    subject_id=task_id,
                    value="drifting",
                    as_of=observed_at + timedelta(minutes=1),
                    authority_class="soft_human",
                ),
            )
            await session.commit()
        async with session_factory() as session:
            current = await session.get(AnsichCurrentBeliefRow, (task_id, "quality"))
            assert current is not None
            selected = await session.get(AnsichBeliefAssertionRow, current.assertion_id)
    finally:
        await service.stop()
        await engine.dispose()

    assert current.resolver_name == "ansich-default"
    assert current.resolver_version == "2.0.0"
    assert selected is not None
    assert selected.authority_class == "soft_human"
    assert selected.value_json == {"value": "drifting"}
