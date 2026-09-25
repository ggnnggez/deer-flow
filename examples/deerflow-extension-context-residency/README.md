# Context residency — independent extension

Records, per task, **which content blocks each model request carried**: the
ordered member inventory of every physical provider call, the logical decision
it belongs to, and every context compaction with the blocks it removed and the
summary it produced. An administrator can then answer the questions a
transcript cannot: when did this block enter the context, how many requests
did it stay in, and what removed it — a compaction, or nothing recorded.

Metadata only. The extension stores content hashes, kinds, sizes and
positions; never message bodies.

## Install and configure

```yaml
# config.yaml
plugins:
  - name: context-residency
    use: deerflow_extension_context_residency:install
    table_prefix: ctxres_
    config:
      enabled: true
      max_attempts: 500        # attempts returned per task read; the response says when it was cut
      queue_capacity: 20000    # buffered events between flushes; a full buffer drops and counts
      flush_interval_ms: 100
```

Install the package next to the host (`deerflow extensions install
examples/deerflow-extension-context-residency`, or pin the wheel) and restart
the Gateway. `table_prefix: ctxres_` keeps the extension's four tables out of
the host's `alembic revision --autogenerate`; the extension creates them itself
at service start. With `database.backend: memory` there is no session factory:
capture stays off and the routes answer `503`.

Requires `deerflow-extension-api` 0.2.6 or later: the compaction event's task
identity and kept hashes, and the summary carrier's `summary_content_hash`
provenance, are what the compaction rows are joined on.

## What it records

| Contribution | Placement | Records |
| --- | --- | --- |
| `DecisionProbe` | `MODEL_LOGICAL`, lead and subagent | One step per logical model decision, whatever the host retries underneath; the effective attempt is the one whose response the decision returned |
| `AttemptProbe` | `MODEL_PHYSICAL`, lead and subagent | One attempt per physical provider call with the exact final request's members: every message (system message first) and every tool schema, in provider order |
| task lifecycle | `on_task_start` / `on_task_stop` | The task row: lead or subagent, parent task, agent name, outcome |
| compaction observer | `on_context_compacted` | The event as emitted: source and kept hashes, output hash, task identity, emission time |

Tables: `ctxres_tasks`, `ctxres_attempts`, `ctxres_members`, `ctxres_compactions`.

### Identity

A member's identity is a hash of what the request carried — the task, the
block's kind and role, the canonical hash of its content, and a tie-breaker.
Messages that reached the request from state carry a stable LangGraph id and
use it. Messages a middleware injected on the way to the provider usually have
none; those are told apart by their occurrence index among identical injections
in the same request, so a reminder re-injected with the same text every turn
reads as one block present across turns. Tool schemas are keyed by name.

Kinds come from the host's provenance stamps first (`memory`,
`skill_instruction`, `durable_context`, `image_or_attachment`,
`middleware_injection`; a coalesced system message stays `system_prompt`; a
message that declares the summary it carries is `summary`) and from the message
role otherwise (`system_prompt`, `user_input`, `assistant_output`,
`tool_request`, `tool_result_visible`). A stamp this build does not know passes
through verbatim: the reader owns the neutral degrade, and history is never
corrected into the nearest lane.

Sizes are the estimator's (`utf8-bytes-div4@1`) for *this* occurrence and
travel with members, not blocks.

### What it will not claim

- Presence is not precomputed. A block absent from an `incomplete` inventory
  (a member that could not be serialized, or a buffer overflow) is unknown,
  never a removal.
- A compaction is positioned against the attempt stream by the timestamps both
  sides recorded on the same host — recorded order, never a causal inference.
  Its removed and preserved members come from the hashes the event declared,
  and its summary block from the carrier that declares `summary_content_hash`;
  nothing is inferred from "it was there last time and not this time". A
  compaction whose next attempt lies outside the read window is listed as
  `unanchored`, not guessed onto the stream.
- `before_tokens` / `after_tokens` are the recorded totals of the requests on
  either side of the boundary, not the summarizer's own count, which the host
  does not report.
- Nothing here says the model *used* a block; it says the block was in the
  request.

## API

Both routes require an administrator; the host's session authentication
applies and personal access tokens are refused on contributed routes.

| Route | Answer |
| --- | --- |
| `GET /api/context-residency/tasks/{task_id}` | `task`, `attempts` (each with its ordered `members`), `blocks` (identity metadata keyed by block id), `compressions`, `attempts_truncated`, `projection_status` |
| `GET /api/context-residency/threads/{thread_id}/tasks` | The lead and subagent tasks recorded for a conversation |

`404` for an unknown task, `503` while the service is not recording. The
`status` plugin action returns the same `projection_status` counters
(accepted, dropped, flushed, write failures, queue depth).

## Verify

```bash
cd backend && uv run pytest tests/test_context_residency_extension.py -q
uv build --wheel examples/deerflow-extension-context-residency --out-dir /tmp/ctxres-wheel
uv pip install --python backend/.venv/bin/python --no-deps --target /tmp/ctxres-installed /tmp/ctxres-wheel/*.whl
backend/.venv/bin/python examples/deerflow-extension-context-residency/scripts/verify_package.py --installed-dir /tmp/ctxres-installed
```
