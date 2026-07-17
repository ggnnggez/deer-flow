from __future__ import annotations

from datetime import datetime

from ansich.contracts import ControlValue

TERMINAL_CONTROL_VALUES = frozenset({"completed", "failed", "interrupted"})


def should_select_control_candidate(
    *,
    current_value: ControlValue | None,
    current_as_of: datetime | None,
    candidate_value: ControlValue,
    candidate_as_of: datetime,
) -> bool:
    """Return whether hard lifecycle evidence may become the current belief."""

    if current_value is None or current_as_of is None:
        return True
    if current_value in TERMINAL_CONTROL_VALUES:
        return False
    if candidate_as_of < current_as_of:
        return False
    if candidate_value == current_value:
        return True
    if current_value == "unknown":
        return True
    if current_value == "created":
        return candidate_value in {"running", *TERMINAL_CONTROL_VALUES}
    if current_value == "running":
        return candidate_value in TERMINAL_CONTROL_VALUES
    return False
