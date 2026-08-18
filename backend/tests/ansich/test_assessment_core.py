from datetime import UTC, datetime, timedelta

from ansich.assessment.absolute_limit import assess_absolute_limits
from ansich.assessment.action_repetition import (
    ToolAction,
    assess_action_repetition,
    build_step_action,
    step_action_signature,
    tool_action_signature,
)
from ansich.assessment.base import Assessment, EvidenceRef, canonical_config_hash
from ansich.assessment.tool_frequency import ToolOccurrence, assess_tool_frequency
from ansich.belief.resolver import BeliefAssertion, resolve_current_belief
from ansich.budget import TaskBudgetView
from ansich.usage import TaskUsageValue

NOW = datetime(2026, 7, 18, 15, 0, tzinfo=UTC)


def _tool(name: str, args: object, obs_id: str) -> ToolAction:
    return ToolAction(tool_name=name, args=args, evidence_obs_id=obs_id)


def _step(
    step_seq: int,
    *tools: ToolAction,
    occurred_at: datetime | None = None,
):
    return build_step_action(
        step_id=f"step-{step_seq}",
        step_seq=step_seq,
        occurred_at=occurred_at or NOW + timedelta(seconds=step_seq),
        tools=tools,
    )


def test_tool_signature_is_canonical_unicode_numeric_and_secret_filtered() -> None:
    first = tool_action_signature(
        "web_search",
        {
            "query": "cafe\u0301",
            "limit": 1.0,
            "password": "first-secret",
            "nested": {"api_key": "one", "safe": True},
        },
    )
    second = tool_action_signature(
        "web_search",
        {
            "nested": {"safe": True, "api-key": "two"},
            "limit": 1,
            "query": "café",
            "password": "different-secret",
        },
    )

    assert first == second
    assert tool_action_signature("web_search", {"query": ["a", "b"]}) != tool_action_signature(
        "web_search",
        {"query": ["b", "a"]},
    )


def test_parallel_step_signature_is_a_sorted_multiset_and_keeps_duplicates() -> None:
    search = _tool("web_search", {"query": "one"}, "obs-search")
    read = _tool("read_file", {"path": "a.txt"}, "obs-read")

    first = _step(1, search, read)
    reordered = _step(2, read, search)
    duplicated = _step(3, search, search)

    assert first.signature == reordered.signature
    assert first.signature == step_action_signature((search.signature, read.signature))
    assert duplicated.signature != first.signature
    assert duplicated.tool_signatures == (search.signature, search.signature)


def test_exact_repetition_resets_on_changed_arguments_and_only_then_marks_runaway() -> None:
    same = [_step(index, _tool("web_search", {"query": "same"}, f"obs-{index}")) for index in range(1, 4)]
    runaway = assess_action_repetition(
        task_id="task-1",
        steps=same,
        now=NOW + timedelta(minutes=1),
        exact_repetition_window=3,
    )
    changed = assess_action_repetition(
        task_id="task-1",
        steps=[
            *same[:2],
            _step(3, _tool("web_search", {"query": "changed"}, "obs-changed")),
        ],
        now=NOW + timedelta(minutes=1),
        exact_repetition_window=3,
    )

    assert runaway.field_name == "behavior"
    assert runaway.value["value"] == "runaway"
    assert runaway.value["reason"] == "exact_repetition"
    assert runaway.value["repeat_count"] == 3
    assert [item.obs_id for item in runaway.evidence] == ["obs-1", "obs-2", "obs-3"]
    assert runaway.assessor.name == "action-repetition"
    assert runaway.assessor.version == "1.0.0"
    assert len(runaway.config_hash) == 64
    assert changed.value["value"] == "unassessed"
    assert changed.value["repeat_count"] == 1


def test_empty_tool_steps_do_not_become_runaway_evidence() -> None:
    result = assess_action_repetition(
        task_id="task-1",
        steps=[_step(1), _step(2), _step(3)],
        now=NOW,
        exact_repetition_window=3,
    )

    assert result.value == {
        "value": "unassessed",
        "reason": "no_tool_action",
        "repeat_count": 0,
        "window": 3,
        "shadow": False,
    }
    assert result.evidence == ()


def test_tool_frequency_is_only_an_operational_signal_not_runaway() -> None:
    occurrences = tuple(
        ToolOccurrence(
            tool_name="web_search",
            occurred_at=NOW - timedelta(seconds=29 - index),
            evidence_obs_id=f"obs-{index}",
        )
        for index in range(30)
    )

    assessments = assess_tool_frequency(
        task_id="task-1",
        occurrences=occurrences,
        now=NOW,
        window_seconds=300,
        threshold=30,
    )

    assert len(assessments) == 1
    assert assessments[0].field_name == "tool_frequency:web_search"
    assert assessments[0].value["value"] == "high"
    assert assessments[0].value["count"] == 30
    assert all(item.field_name != "behavior" for item in assessments)


def test_absolute_limit_emits_budget_fact_and_shadow_runaway_behavior() -> None:
    budget = TaskBudgetView(
        entity_id="budget-1",
        task_id="task-1",
        dimension="steps",
        aggregation_scope="local",
        warning_limit=80,
        hard_limit=100,
        enforcement=False,
        source_kind="shadow",
        requested_value=None,
        effective_value=100,
        configured_obs_id="obs-budget",
    )
    usage = TaskUsageValue(
        dimension="steps",
        aggregation_scope="local",
        value=101,
        as_of=NOW,
        complete_through_ingest_seq=42,
    )

    result = assess_absolute_limits(
        task_id="task-1",
        budgets=(budget,),
        usage=(usage,),
        now=NOW + timedelta(seconds=1),
        usage_evidence={
            ("steps", "local"): ("obs-step-1", "obs-step-2"),
        },
    )

    assert len(result.budget_health) == 1
    assert result.budget_health[0].value == {
        "value": "exceeded",
        "dimension": "steps",
        "aggregation_scope": "local",
        "usage_value": 101,
        "warning_limit": 80,
        "hard_limit": 100,
        "overshoot": 1,
        "enforcement": False,
        "shadow": True,
    }
    assert result.behavior.value["value"] == "runaway"
    assert result.behavior.value["reason"] == "absolute_limit"
    assert result.behavior.value["shadow"] is True
    assert [item.obs_id for item in result.behavior.evidence] == [
        "obs-budget",
        "obs-step-1",
        "obs-step-2",
    ]


def test_absolute_limit_does_not_claim_healthy_or_runaway_with_incomplete_usage() -> None:
    budget = TaskBudgetView(
        entity_id="budget-1",
        task_id="task-1",
        dimension="total_tokens",
        aggregation_scope="local",
        warning_limit=80,
        hard_limit=100,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=100,
        configured_obs_id="obs-budget",
    )
    usage = TaskUsageValue(
        dimension="total_tokens",
        aggregation_scope="local",
        value=200,
        as_of=NOW,
        complete_through_ingest_seq=42,
    )

    result = assess_absolute_limits(
        task_id="task-1",
        budgets=(budget,),
        usage=(usage,),
        now=NOW,
        usage_complete=False,
    )

    assert result.budget_health[0].value["value"] == "unknown"
    assert result.behavior.value["value"] == "unassessed"


def test_non_runaway_budget_dimensions_do_not_promote_behavior() -> None:
    budget = TaskBudgetView(
        entity_id="budget-child-tasks",
        task_id="task-1",
        dimension="child_tasks_spawned",
        aggregation_scope="local",
        warning_limit=4,
        hard_limit=6,
        enforcement=True,
        source_kind="release_default",
        requested_value=None,
        effective_value=6,
        configured_obs_id="obs-child-budget",
    )
    usage = TaskUsageValue(
        dimension="child_tasks_spawned",
        aggregation_scope="local",
        value=7,
        as_of=NOW,
        complete_through_ingest_seq=44,
    )

    result = assess_absolute_limits(
        task_id="task-1",
        budgets=(budget,),
        usage=(usage,),
        now=NOW,
    )

    assert result.budget_health[0].value["value"] == "exceeded"
    assert result.behavior.value["value"] == "unassessed"


def _assertion(
    assertion_id: str,
    *,
    value: str,
    as_of: datetime,
    authority_class: str,
    fidelity_class: str,
) -> BeliefAssertion:
    assessment = Assessment(
        subject_id="task-1",
        field_name="behavior",
        value={"value": value},
        as_of=as_of,
        asserted_at=as_of,
        assessor={"name": f"{authority_class}-source", "version": "1.0.0"},
        config_hash=canonical_config_hash({"source": authority_class}),
        authority_class=authority_class,
        fidelity_class=fidelity_class,
        evidence=(EvidenceRef(obs_id=f"obs-{assertion_id}"),),
    )
    return BeliefAssertion.from_assessment(assessment, assertion_id=assertion_id)


def test_resolver_uses_authority_then_as_of_and_never_regresses_on_late_commit() -> None:
    rule_new = _assertion(
        "assertion-rule-new",
        value="runaway",
        as_of=NOW,
        authority_class="configured_rule",
        fidelity_class="rule",
    )
    human_old = _assertion(
        "assertion-human-old",
        value="on_track",
        as_of=NOW - timedelta(days=1),
        authority_class="human_override",
        fidelity_class="hard",
    )
    later_committed_but_older_evidence = _assertion(
        "assertion-rule-old",
        value="drifting",
        as_of=NOW - timedelta(hours=1),
        authority_class="configured_rule",
        fidelity_class="rule",
    ).model_copy(update={"asserted_at": NOW + timedelta(hours=1)})

    human_resolution = resolve_current_belief((rule_new, human_old))
    rule_resolution = resolve_current_belief(
        (rule_new, later_committed_but_older_evidence),
    )

    assert human_resolution.selected.assertion_id == "assertion-human-old"
    assert rule_resolution.selected.assertion_id == "assertion-rule-new"
    assert human_resolution.resolver.name == "ansich-default"
    assert human_resolution.resolver.version == "2.0.0"


def test_resolver_uses_stable_assertion_id_as_the_final_tie_breaker() -> None:
    first = _assertion(
        "assertion-a",
        value="drifting",
        as_of=NOW,
        authority_class="automated",
        fidelity_class="soft",
    )
    second = first.model_copy(
        update={"assertion_id": "assertion-b", "value": {"value": "stuck"}},
    )

    resolved = resolve_current_belief((second, first))

    assert resolved.selected.assertion_id == "assertion-b"
