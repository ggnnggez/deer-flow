"""Pure-rule tests for ``environment-pressure@1``.

Every case here is a function call — no service, no database, no clock. The
periodic wiring that feeds these functions is covered by
``test_environment_alerts.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ansich.assessment.base import canonical_config_hash
from ansich.environment import (
    EnvironmentThresholds,
    assess_environment_leak,
    assess_environment_pressure,
)

_NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)
_SCOPE_ID = "scope-under-test"
_THRESHOLDS = EnvironmentThresholds()


def _pressure(
    *,
    metric: str = "fd_open",
    latest_value: int = 100,
    limit: int | None = 1024,
    coverage: str = "continuous",
    environment_scope: str = "container",
    as_of: datetime | None = None,
    now: datetime = _NOW,
    last_obs_id: str | None = "obs-1",
    sample_interval_seconds: int = 10,
    thresholds: EnvironmentThresholds = _THRESHOLDS,
):
    return assess_environment_pressure(
        scope_id=_SCOPE_ID,
        metric=metric,
        environment_scope=environment_scope,
        coverage=coverage,
        latest_value=latest_value,
        limit=limit,
        as_of=as_of or now,
        last_obs_id=last_obs_id,
        now=now,
        sample_interval_seconds=sample_interval_seconds,
        thresholds=thresholds,
    )


def _leak(
    *,
    environment_scope: str = "container",
    coverage: str = "continuous",
    consecutive_growth_count: int = 6,
    growth_started_at: datetime | None = _NOW - timedelta(seconds=70),
    window_min_value: int = 100,
    latest_value: int = 160,
    as_of: datetime = _NOW,
    now: datetime = _NOW,
    last_obs_id: str | None = "obs-leak",
    thresholds: EnvironmentThresholds = _THRESHOLDS,
):
    return assess_environment_leak(
        scope_id=_SCOPE_ID,
        environment_scope=environment_scope,
        coverage=coverage,
        consecutive_growth_count=consecutive_growth_count,
        growth_started_at=growth_started_at,
        window_min_value=window_min_value,
        latest_value=latest_value,
        as_of=as_of,
        last_obs_id=last_obs_id,
        now=now,
        thresholds=thresholds,
    )


def test_thresholds_mirror_the_config_defaults() -> None:
    assert _THRESHOLDS.fd_warn_ratio == 0.8
    assert _THRESHOLDS.fd_critical_ratio == 0.95
    assert _THRESHOLDS.disk_free_warn_ratio == 0.10
    assert _THRESHOLDS.disk_free_critical_ratio == 0.05
    assert _THRESHOLDS.psi_warn_milli == 40_000
    assert _THRESHOLDS.psi_critical_milli == 80_000
    assert _THRESHOLDS.leak_min_samples == 6
    assert _THRESHOLDS.leak_window_seconds == 60
    assert _THRESHOLDS.leak_min_growth == 50


def test_thresholds_reject_inverted_ordering() -> None:
    with pytest.raises(ValueError):
        EnvironmentThresholds(fd_warn_ratio=0.96, fd_critical_ratio=0.95)
    with pytest.raises(ValueError):
        EnvironmentThresholds(psi_warn_milli=90_000, psi_critical_milli=80_000)
    with pytest.raises(ValueError):
        EnvironmentThresholds(
            disk_free_warn_ratio=0.05,
            disk_free_critical_ratio=0.10,
        )


def test_fd_below_warn_ratio_is_ok() -> None:
    assessment = _pressure(latest_value=100, limit=1024)
    assert assessment is not None
    assert assessment.value["value"] == "ok"
    assert assessment.field_name == "environment_pressure:fd_open"
    assert assessment.subject_id == _SCOPE_ID
    assert assessment.assessor.name == "environment-pressure"
    assert assessment.assessor.version == "1"
    assert assessment.authority_class == "configured_rule"
    assert assessment.fidelity_class == "rule"
    assert [item.obs_id for item in assessment.evidence] == ["obs-1"]


def test_fd_at_warn_ratio_is_warning() -> None:
    assessment = _pressure(latest_value=850, limit=1024)
    assert assessment is not None
    assert assessment.value["value"] == "warning"


def test_fd_at_critical_ratio_is_critical() -> None:
    assessment = _pressure(latest_value=990, limit=1024)
    assert assessment is not None
    assert assessment.value["value"] == "critical"


def test_fd_without_limit_is_unknown() -> None:
    assessment = _pressure(latest_value=990, limit=None)
    assert assessment is not None
    assert assessment.value["value"] == "unknown"


def test_fd_with_non_positive_limit_is_unknown() -> None:
    assessment = _pressure(latest_value=990, limit=0)
    assert assessment is not None
    assert assessment.value["value"] == "unknown"


def test_uninstrumented_coverage_is_unknown_never_ok() -> None:
    assessment = _pressure(latest_value=1, limit=1024, coverage="uninstrumented")
    assert assessment is not None
    assert assessment.value["value"] == "unknown"
    assert assessment.value["coverage"] == "uninstrumented"


def test_stale_continuous_reading_is_unknown() -> None:
    assessment = _pressure(
        latest_value=1,
        limit=1024,
        sample_interval_seconds=10,
        as_of=_NOW - timedelta(seconds=31),
    )
    assert assessment is not None
    assert assessment.value["value"] == "unknown"


def test_reading_inside_three_intervals_still_reports_its_state() -> None:
    assessment = _pressure(
        latest_value=1,
        limit=1024,
        sample_interval_seconds=10,
        as_of=_NOW - timedelta(seconds=29),
    )
    assert assessment is not None
    assert assessment.value["value"] == "ok"


def test_per_command_coverage_produces_no_pressure_assertion() -> None:
    assert _pressure(coverage="per_command", environment_scope="process_group") is None


def test_disk_free_ratio_direction_is_inverted() -> None:
    warning = _pressure(metric="disk_free_bytes", latest_value=8, limit=100)
    critical = _pressure(metric="disk_free_bytes", latest_value=3, limit=100)
    healthy = _pressure(metric="disk_free_bytes", latest_value=50, limit=100)
    assert warning is not None and warning.value["value"] == "warning"
    assert critical is not None and critical.value["value"] == "critical"
    assert healthy is not None and healthy.value["value"] == "ok"


@pytest.mark.parametrize(
    "metric",
    ["psi_io_some_avg10_milli", "psi_memory_some_avg10_milli"],
)
def test_psi_thresholds(metric: str) -> None:
    warning = _pressure(metric=metric, latest_value=50_000, limit=None)
    critical = _pressure(metric=metric, latest_value=90_000, limit=None)
    healthy = _pressure(metric=metric, latest_value=100, limit=None)
    assert warning is not None and warning.value["value"] == "warning"
    assert critical is not None and critical.value["value"] == "critical"
    assert healthy is not None and healthy.value["value"] == "ok"


def test_metric_without_a_v1_rule_produces_no_assertion() -> None:
    assert _pressure(metric="io_read_bytes", latest_value=10**9, limit=None) is None
    assert _pressure(metric="io_write_bytes", latest_value=10**9, limit=None) is None


def test_pressure_value_carries_only_stable_categorical_fields() -> None:
    assessment = _pressure(latest_value=990, limit=1024)
    assert assessment is not None
    assert set(assessment.value) == {
        "value",
        "metric",
        "environment_scope",
        "coverage",
    }
    assert "latest_value" not in assessment.value
    assert "limit" not in assessment.value
    assert "task_id" not in assessment.value
    assert "possibly_affected_task_ids" not in assessment.value


def test_pressure_value_is_identical_across_two_different_readings() -> None:
    first = _pressure(latest_value=990, limit=1024, last_obs_id="obs-a")
    second = _pressure(latest_value=1000, limit=1024, last_obs_id="obs-b")
    assert first is not None and second is not None
    # Same categorical state, different numbers and different evidence: the
    # value dicts must be equal, which is what makes transition-only appending
    # possible at the persistence layer.
    assert first.value == second.value


def test_pressure_config_hash_is_the_canonical_threshold_hash() -> None:
    assessment = _pressure()
    assert assessment is not None
    assert assessment.config_hash == canonical_config_hash(_THRESHOLDS.model_dump())


def test_pressure_config_hash_moves_when_a_threshold_moves() -> None:
    other = EnvironmentThresholds(fd_warn_ratio=0.5)
    assessment = _pressure()
    shifted = _pressure(thresholds=other)
    assert assessment is not None and shifted is not None
    assert assessment.config_hash != shifted.config_hash


def test_pressure_without_evidence_keeps_an_empty_evidence_tuple() -> None:
    assessment = _pressure(coverage="uninstrumented", last_obs_id=None)
    assert assessment is not None
    assert assessment.value["value"] == "unknown"
    assert assessment.evidence == ()


def test_pressure_rejects_non_positive_sample_interval() -> None:
    with pytest.raises(ValueError):
        _pressure(sample_interval_seconds=0)


def test_leak_suspected_on_sustained_growth() -> None:
    assessment = _leak()
    assert assessment is not None
    assert assessment.value["value"] == "suspected"
    assert assessment.field_name == "environment_leak:fd_open"
    assert assessment.subject_id == _SCOPE_ID
    assert assessment.assessor.name == "environment-pressure"
    assert [item.obs_id for item in assessment.evidence] == ["obs-leak"]


def test_leak_rejects_process_group_and_host_shared_inputs() -> None:
    assert _leak(environment_scope="process_group") is None
    assert _leak(environment_scope="host_shared") is None


def test_leak_rejects_non_continuous_coverage() -> None:
    assert _leak(coverage="per_command") is None
    assert _leak(coverage="uninstrumented") is None


def test_leak_below_min_samples_is_none() -> None:
    assessment = _leak(consecutive_growth_count=5)
    assert assessment is not None
    assert assessment.value["value"] == "none"


def test_leak_below_min_growth_is_none() -> None:
    assessment = _leak(window_min_value=100, latest_value=149)
    assert assessment is not None
    assert assessment.value["value"] == "none"


def test_leak_uses_the_current_runs_baseline_not_a_lifetime_dip() -> None:
    """A run-scoped baseline keeps an old dip from manufacturing a suspicion.

    Shaped like the container that starts at fd=50 and settles at a working set
    of 400: six growing samples spanning 70s that add only +7 in total. With
    the projector's post-fix ``window_min_value`` (the current run's own
    starting value, 400) this is net growth of 7 against a
    ``leak_min_growth`` of 50, so the rule must say "none". A lifetime minimum
    of 50 would have made the same inputs read as 357 of growth.
    """

    assessment = _leak(window_min_value=400, latest_value=407)
    assert assessment is not None
    assert assessment.value["value"] == "none"


def test_leak_below_window_span_is_none() -> None:
    assessment = _leak(growth_started_at=_NOW - timedelta(seconds=59))
    assert assessment is not None
    assert assessment.value["value"] == "none"


def test_leak_without_growth_anchor_is_none() -> None:
    assessment = _leak(growth_started_at=None)
    assert assessment is not None
    assert assessment.value["value"] == "none"


def test_leak_on_stale_data_is_unknown() -> None:
    assessment = _leak(as_of=_NOW - timedelta(seconds=61))
    assert assessment is not None
    assert assessment.value["value"] == "unknown"


def test_leak_value_carries_only_stable_categorical_fields() -> None:
    assessment = _leak()
    assert assessment is not None
    assert set(assessment.value) == {
        "value",
        "metric",
        "environment_scope",
        "coverage",
    }
    assert assessment.value["metric"] == "fd_open"


def test_leak_config_hash_is_the_canonical_threshold_hash() -> None:
    assessment = _leak()
    assert assessment is not None
    assert assessment.config_hash == canonical_config_hash(_THRESHOLDS.model_dump())


def test_config_mapping_threads_every_environment_threshold() -> None:
    """Every ``environment_*`` assessor knob must reach the rule model.

    A knob silently left out of the mapper would be invisible: the rule would
    keep running on its default and the operator's setting would do nothing.
    """

    from deerflow.ansich import environment_thresholds_from_config
    from deerflow.config.ansich_config import AnsichAssessorConfig

    assessors = AnsichAssessorConfig(
        environment_fd_warn_ratio=0.6,
        environment_fd_critical_ratio=0.7,
        environment_disk_free_warn_ratio=0.4,
        environment_disk_free_critical_ratio=0.2,
        environment_psi_warn_milli=11_000,
        environment_psi_critical_milli=22_000,
        environment_leak_min_samples=3,
        environment_leak_window_seconds=17,
        environment_leak_min_growth=9,
    )
    assert environment_thresholds_from_config(assessors) == EnvironmentThresholds(
        fd_warn_ratio=0.6,
        fd_critical_ratio=0.7,
        disk_free_warn_ratio=0.4,
        disk_free_critical_ratio=0.2,
        psi_warn_milli=11_000,
        psi_critical_milli=22_000,
        leak_min_samples=3,
        leak_window_seconds=17,
        leak_min_growth=9,
    )
    # Defaults must survive the mapping unchanged too.
    assert environment_thresholds_from_config(AnsichAssessorConfig()) == EnvironmentThresholds()
