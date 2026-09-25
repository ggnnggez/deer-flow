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
      stale_task_after_minutes: 60   # a task with no stop event after this long is flagged on the health tab
      # context_windows: {deepseek-v4-flash: 128000}   # fallback when the model config declares no context_window
      # default_context_window: 128000                  # fallback for every other model
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

Each attempt also records the model's **context window** when the host knows
it: the run's configured model's `context_window` from `config.yaml` (the same
field the summarization fraction trigger uses) while that entry names the
provider model that actually ran — the host falls back to its default model
when a request is not on the allowlist, and then the provider model id is
matched against the configured models instead — else the plugin's own
`context_windows` map (by configured name or provider model id), else
`default_context_window`. A window is never guessed from a model name; an
unknown window is stored as absent and the page says so.

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

## The page

The package ships a workspace page (`assets-v1`): **Context residency** in the
sidebar, at `/workspace/extensions/community.context-residency/board`, plus a
conversation-menu action that opens the page for the current conversation. It
has three tabs:

- **Tasks** — the index of every recorded task: filter by kind, outcome, time
  range, compactions or incomplete inventories; group by conversation (leads
  first, subagents indented under their parent) or flat; sort by start, duration,
  attempts, compactions, incomplete inventories or peak context; 50 per page.
  Each row carries steps / attempts (with retries), compaction count, inventory
  completeness, and the peak request's size, composition by lane and share of the
  window. The search box matches task id, conversation id or agent name;
  pasting a full task id opens its board directly, even outside the current
  filters. `?q=<text>` (or `?thread=<id>` from the conversation action) seeds the
  query, `?task=<id>` opens a board (optionally `?step=<seq>`), `?tab=health`
  opens the health tab.
- **Health** — the extension's own recording state, refreshed every 15 s while
  open: recording / not recording, database and table prefix, last write and
  event, uptime; queue depth, accepted, written, dropped and write-failure
  counters; write throughput per minute for the last hour; row counts per table
  and the database file; inventory completeness, compaction positioning and
  stale tasks; diagnostics with a remedy each (dropped events, write failures,
  buffer pressure, stale tasks, unanchored compactions, incomplete inventories,
  contract); and a read-only echo of the plugin configuration. A warning dot on
  the tab means a diagnostic is not `ok`.
- **Board** — one task: a per-request composition band by lane, a block ×
  request residency matrix, and a drill panel (request → block → compaction).
  Presence cells follow the rules above — an unknown cell is drawn as `?`, never
  as absent. The request panel's **composition bar treats the model's context
  window as 100%**: each lane shows its absolute share of the window, the rest of
  the bar is free, and a request larger than the window is flagged with how far
  it overflows. When no window was recorded the bar falls back to the request as
  100% and says so; the member list always shows shares of the request.

The page is a self-contained React bundle: `frontend/` holds the sources, and
`pnpm --dir frontend install && pnpm --dir frontend build` writes
`deerflow_extension_context_residency/static/dist/{index.mjs,styles.css}`, the
two files `ui_manifest.json` lists. The built files are committed so the wheel
installs without a JavaScript toolchain; rebuild them after changing
`frontend/src`. It mounts inside the host's Shadow DOM with its own stylesheet
and follows the host theme through the host's CSS variables. Hosts older than
extension API 0.2.3 refuse `BrowserAssets`; the package logs that and installs
capture and the admin API without the page.

## API

All routes require an administrator; the host's session authentication
applies and personal access tokens are refused on contributed routes.

| Route | Answer |
| --- | --- |
| `GET /api/context-residency/tasks` | The task index: `tasks` (each task with `steps`, `attempts`, `incomplete_attempts`, `compactions`, `peak_tokens`, `peak_attempt_id`, `peak_context_window`, `peak_by_kind`, `last_attempt_at`, `duration_seconds`), `total`, `limit`, `offset`, `sort`, `direction`, `projection_status`. Query: `query` (task id, conversation id or agent name substring), `kind`, `outcome` (`running` = no stop event recorded), `since` (ISO), `has_compactions`, `incomplete_only`, `sort` (`started`, `last`, `duration`, `attempts`, `compactions`, `incomplete`, `peak`), `direction`, `limit` (≤ 500), `offset` |
| `GET /api/context-residency/tasks/{task_id}` | `task`, `attempts` (each with its ordered `members` and `context_window_tokens`), `blocks` (identity metadata keyed by block id), `compressions`, `attempts_truncated`, `projection_status` |
| `GET /api/context-residency/threads/{thread_id}/tasks` | The lead and subagent tasks recorded for a conversation |
| `GET /api/context-residency/health` | `status` (the counters plus queue capacity, timestamps of the last write, event and drop, uptime, last batch, per-minute `throughput`), `storage` (backend, database, file size, row counts, earliest record), `quality` (complete / incomplete attempts, positioned / unanchored compactions, open and stale tasks), `diagnostics` (`level`, `code`, `title`, `detail`, `remedy`, `affected`), `config` (the options, versions and placements). Answers `200` even while not recording, with `storage` and `quality` null |

`404` for an unknown task, `503` from the task routes while the service is not
recording. The `status` plugin action returns the same `projection_status`
counters (accepted, dropped, flushed, write failures, queue depth).

## Verify

```bash
pnpm --dir examples/deerflow-extension-context-residency/frontend install
pnpm --dir examples/deerflow-extension-context-residency/frontend test
pnpm --dir examples/deerflow-extension-context-residency/frontend build
cd backend && uv run pytest tests/test_context_residency_extension.py -q
uv build --wheel examples/deerflow-extension-context-residency --out-dir /tmp/ctxres-wheel
uv pip install --python backend/.venv/bin/python --no-deps --target /tmp/ctxres-installed /tmp/ctxres-wheel/*.whl
backend/.venv/bin/python examples/deerflow-extension-context-residency/scripts/verify_package.py --installed-dir /tmp/ctxres-installed
```
