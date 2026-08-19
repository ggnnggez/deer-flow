#!/usr/bin/env bash
#
# MANUAL diagnostic for the F10-10 settle-timing flakes. NOT a test, NOT run by
# CI, NOT imported by anything. Nothing collects this file; you run it by hand.
#
# WHEN TO USE IT
#   When one of the gated settle-family tests rotates red again. F10-10's own
#   instruction is "capture the failure text before fixing" -- this script is how
#   you make the failure happen on demand instead of waiting for a full-suite run
#   to catch it. Failing rounds are saved whole, so the text survives.
#
# PROVENANCE
#   This is the reproduction Task 8 used as its acceptance evidence for F10-10
#   (see the F10-10 section of ansich/docs/plans/phase-10-review-followups.md):
#   under 24 CPU busy loops,
#   `test_sql_budget_health_retains_terminal_overshoot_and_evidence` failed
#   8 out of 8 rounds before the `only_test_driven_assessments` gate landed and
#   0 out of 8 after it, with the same failure text the session had recorded by
#   hand. The addendum keeps those numbers but describes the method only in
#   prose; this file makes it re-runnable.
#
# WHAT THE ADDENDUM DOES NOT SAY, AND WHAT THIS FILE ASSUMES
#   * Hog shape: the addendum says "24 CPU busy loops" and nothing more. Here
#     each hog is one `while :; do :; done` subshell -- no niceness, no memory or
#     IO pressure. A machine with fewer cores than hogs is the point, not a bug.
#   * Rounds: 8, inferred from the recorded "8/8" figures. Override with $1.
#   * Batching: all target tests run in ONE pytest process per round. Suite-level
#     load is part of what these tests are sensitive to, so splitting them into
#     one process each would weaken the reproduction.
#   * Nothing here pins a seed or an order; the flakes are timing-driven, so a
#     round that passes proves nothing on its own. Read the totals, not a round.
#
# USAGE
#   backend/tests/support/ansich_contention_repro.sh [ROUNDS] [HOGS] [pytest-target...]
#     ROUNDS  rounds to run (default 8)
#     HOGS    CPU busy loops to hold up during the run (default 24)
#     targets pytest node ids; defaults to the four tests F10-10 names as its
#             evidence. F10-10's "later observation" bullet names two more that
#             still rotated red under Task 9's heavier load -- pass them
#             explicitly when that is what you are chasing:
#               tests/ansich/test_sql_safety.py::test_scope_safety_reassessment_work_does_not_grow_with_tool_call_count
#               tests/ansich/test_sql_alerts.py::test_failed_assessor_jobs_degrade_health_and_can_be_retried
#
#   Requires only `uv` and this repo -- no postgres, no docker. Expect roughly a
#   minute per round on a loaded machine.
#
set -u

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUNDS="${1:-8}"
HOGS="${2:-24}"
if [ "$#" -gt 2 ]; then
    shift 2
    TARGETS=("$@")
else
    # The four tests F10-10 lists as its evidence, in the order the addendum
    # diagnoses them.
    TARGETS=(
        "tests/ansich/test_sql_budget.py::test_sql_budget_health_retains_terminal_overshoot_and_evidence"
        "tests/ansich/test_sql_alerts.py::test_sql_assessor_jobs_coalesce_to_highest_pending_watermark"
        "tests/ansich/test_sql_safety.py::test_absorbed_low_watermark_window_survives_an_evaluation_rollback"
        "tests/ansich/test_sql_task_lifecycle.py::test_step_attempt_and_context_are_queryable_after_projection"
    )
fi

OUT_DIR="$(mktemp -d -t ansich-contention-XXXXXX)"
hog_pids=()

cleanup() {
    # Hogs are unkillable-looking busy loops; leaving even one behind silently
    # taxes the machine for the rest of the session. EXIT covers the normal end,
    # INT/TERM cover Ctrl-C and a kill of this script.
    if [ "${#hog_pids[@]}" -gt 0 ]; then
        kill "${hog_pids[@]}" 2>/dev/null
        wait "${hog_pids[@]}" 2>/dev/null
    fi
}
# INT/TERM must also *stop*: without the explicit exit the loop would keep
# running its remaining rounds unloaded (hogs dead) and count them as data.
trap cleanup EXIT
trap 'trap - EXIT; cleanup; exit 130' INT
trap 'trap - EXIT; cleanup; exit 143' TERM

cd "$BACKEND_DIR" || exit 1

echo "backend:  $BACKEND_DIR"
echo "rounds:   $ROUNDS"
echo "hogs:     $HOGS (this machine reports $( (nproc 2>/dev/null) || echo '?') cpus)"
echo "targets:  ${#TARGETS[@]}"
for target in "${TARGETS[@]}"; do
    echo "          $target"
done
echo "failures saved under: $OUT_DIR"
echo

for _ in $(seq "$HOGS"); do
    ( while :; do :; done ) &
    hog_pids+=($!)
done

failures=0
for round in $(seq "$ROUNDS"); do
    # -p no:cacheprovider keeps repeated runs from reordering themselves via
    # .pytest_cache, which would make rounds non-comparable.
    output="$(uv run pytest -q -p no:cacheprovider "${TARGETS[@]}" 2>&1)"
    status=$?
    if [ "$status" -ne 0 ]; then
        failures=$((failures + 1))
        printf '%s' "$output" > "$OUT_DIR/round_$round.txt"
        echo "round $round: FAIL (status=$status) -> $OUT_DIR/round_$round.txt"
        printf '%s\n' "$output" | grep -E '^(FAILED|ERROR)' | sed 's/^/    /'
    else
        echo "round $round: pass"
    fi
    printf '%s\n' "$output" | tail -1 | sed 's/^/    /'
done

echo
echo "TOTAL FAILURES: $failures / $ROUNDS"
if [ "$failures" -gt 0 ]; then
    echo "Read the saved rounds before changing anything -- F10-10's standing rule"
    echo "is failure text first, diagnosis second."
    exit 1
fi
rmdir "$OUT_DIR" 2>/dev/null
exit 0
