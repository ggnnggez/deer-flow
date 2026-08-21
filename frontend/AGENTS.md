# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with the DeerFlow frontend. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

## Project Overview

DeerFlow Frontend is a Next.js 16 web interface for an AI agent system. It communicates with a LangGraph-based backend to provide thread-based AI conversations with streaming responses, artifacts, and a skills/tools system.

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2. Requires Node.js 22+ and pnpm 10.26.2+.

### Core dependencies

- **LangGraph SDK** (`@langchain/langgraph-sdk` ^1.5.3) — Agent orchestration and streaming
- **LangChain Core** (`@langchain/core` ^1.1.15) — Fundamental AI building blocks
- **TanStack Query** (`@tanstack/react-query` ^5.90.17) — Server state management
- **TanStack Virtual** (`@tanstack/react-virtual` ^3.13.23) — Long Trajectory list virtualization
- **UI**: Shadcn UI, MagicUI, React Bits, and Vercel AI SDK elements (generated from registries — see Code Style)

## Commands

| Command          | Purpose                                           |
| ---------------- | ------------------------------------------------- |
| `pnpm dev`       | Dev server with Turbopack (http://localhost:3000) |
| `pnpm build`     | Production build                                  |
| `pnpm check`     | Lint + type check (run before committing)         |
| `pnpm lint`      | ESLint only                                       |
| `pnpm lint:fix`  | ESLint with auto-fix                              |
| `pnpm format`    | Prettier check (`pnpm format:write` to apply)     |
| `pnpm test`      | Run unit tests with Rstest                        |
| `pnpm test:e2e`  | Run E2E tests with Playwright (Chromium)          |
| `pnpm typecheck` | TypeScript type check (`tsc --noEmit`)            |
| `pnpm start`     | Start production server                           |

Unit tests live under `tests/unit/` and mirror the `src/` layout (e.g., `tests/unit/core/api/stream-mode.test.ts` tests `src/core/api/stream-mode.ts`). Powered by Rstest; import source modules via the `@/` path alias.

E2E tests live under `tests/e2e/` and use Playwright with Chromium. They mock all backend APIs via `page.route()` network interception and test real page interactions (navigation, chat input, streaming responses). Config: `playwright.config.ts`.

## Architecture

```
Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_agent)
                                              ├── Sub-Agents
                                              └── Tools & Skills
```

The frontend is a stateful chat application. Users create **threads** (conversations), send messages, set thread-scoped `/goal` completion conditions, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code), **todos**, and goal state updates.

### Source Layout (`src/`)

- **`app/`** — Next.js App Router. Routes include `/` (landing), `/workspace/chats/[thread_id]` (chat), `/workspace/agents/[agent_name]` and `/workspace/agents/new` (custom agents), admin-only Ansich operations at `/workspace/ansich/operations` and `/workspace/ansich/tasks/[task_id]`, `/blog/…`, the `(auth)/{login,setup,auth/callback}` flow, `/[lang]/docs/…`, and `/api/…` route handlers (e.g. `/api/memory`).
- **`components/`** — React components:
  - `ui/` — Shadcn UI primitives (auto-generated, ESLint-ignored)
  - `ai-elements/` — Vercel AI SDK elements (auto-generated, ESLint-ignored)
  - `workspace/` — Chat page components (messages, artifacts, settings, trajectory)
  - `landing/` — Landing page sections
  - `docs/` — Docs / MDX rendering components
- **`core/`** — Business logic, the heart of the app. Domains include `threads/` (creation, streaming, state), `api/` (LangGraph client singleton), `agents/` (custom agents), `ansich/` (typed admin observability API, 5-second TanStack queries, health/error preservation, and pure presentation helpers), `auth/` (authentication), `artifacts/`, `channels/` (IM connections), `i18n/` (en-US, zh-CN), `settings/`, `memory/`, `skills/`, `messages/`, `mcp/`, `models/`, `trajectory/` (pure message-to-turn projection and flattened search/fold rows), `input-polish/` (pre-send draft rewrite API), `voice-input/` (browser speech-recognition helpers), `suggestions/`, `tasks/`, `todos/`, `tools/`, `workspace-changes/` (run-scoped changed-file summaries and diff fetching), `config/`, `notification/`, `blog/`, plus rendering helpers (`rehype/`, `streamdown/`) and `utils/`.
- **`hooks/`** — Shared React hooks
- **`lib/`** — Utilities (`cn()` from clsx + tailwind-merge)
- **`content/`** — MDX content (blog posts, docs) rendered by the app
- **`styles/`** — Global CSS with Tailwind v4 `@import` syntax and CSS variables for theming
- **`typings/`** — Ambient TypeScript declarations
- Root files: `env.js` (env validation), `mdx-components.ts` (MDX component map)

### Data Flow

1. Optional composer helpers such as `core/input-polish` can rewrite the local draft before submission, and `core/voice-input` can transcribe browser microphone input into that same local draft; confirmed user input then flows to thread hooks (`core/threads/hooks.ts`) → LangGraph SDK streaming
2. Stream events update thread state (messages, artifacts, todos, goal)
3. `useThreadHistory` loads persisted conversation pages from `GET /api/threads/{id}/messages/page`, preserving the backend's thread-global event `seq`; rendering overlays checkpoint/live copies at their matching canonical identities (a summarized checkpoint may contain a protected early input plus a recent tail), suppresses checkpoint/transient prefixes whose canonical position is still behind an unloaded cursor page instead of collapsing that unknown gap before a recent anchor, then adds optimistic messages without timestamp re-sorting. History invalidation preserves already-loaded pages so their established ordering positions are not discarded.
4. Conversation pages can render the same ordered `thread.messages` as Chat or Trajectory. `core/trajectory/projector.ts` groups visible messages at human-message boundaries, numbers each AI message as a model Step, joins tool results by `tool_call_id`, derives Tool error/success only from the recorded result status, and aggregates only recorded usage and duration metadata. `core/threads/hooks.ts` converts journal completion timestamps plus `latency_ms`/`ttft_ms` into server-owned `additional_kwargs.trajectory_timing` and preserves that payload when checkpoint/live messages overlay history. `core/trajectory/timeline.ts` builds one absolute domain across measured Assistant and Tool records, groups Tool lanes by name, and exposes the TTFT fraction without estimating missing timing. A call without a result is `running` only while the page's thread stream is active and is `incomplete` after the stream settles. `components/workspace/trajectory/trajectory-view.tsx` owns the measured swimlane, search, folding, structured detail inspection, history loading, tail following, and virtualized rows. It must not infer unavailable timing or prompt data.
5. Stop actions call the LangGraph SDK stream stop path; `core/threads/hooks.ts` invalidates current-thread, thread-history, token-usage, and sidebar/search caches immediately and schedules one follow-up refetch because SDK stop may finish via abort + fire-and-forget cancel before backend title finalization commits
6. TanStack Query manages server state; localStorage stores user settings
7. Components subscribe to thread state and render updates

Ansich is deliberately separate from chat state. The sidebar entry is rendered
only for `system_role="admin"`; this is a convenience boundary, while Gateway
admin authorization remains authoritative. The Phase 5 operations list polls
its active-task read model every 5 seconds while any Task is running, backs off
to 10 seconds when empty, and pauses while the page is hidden. Operations keeps
this live lens under “Running” and exposes terminal Tasks under a separate,
non-polling, cursor-paged “Task history” tab; history filtering happens in the
Gateway before pagination. Task detail stops
automatic polling after its Task becomes terminal. Both render full Belief
provenance plus projection health (`watermark`, lag, failed jobs, and lost
ranges). Unknown heartbeat, Usage, or Budget evidence must be shown as
insufficient evidence rather than healthy; Budget bars exist only when a limit
and complete Usage are both known, and may show terminal overshoot. Phase 8 adds
a collapsible Task tree to Overview, local/inclusive Usage scope selection and a
source-Task breakdown to Budgets, and child producer links in Context lineage.
History requests `root_only=true` so delegated children are discovered through
their parent tree rather than duplicated as top-level history rows. These views
must not derive end-user progress percentages or fake Step counts. **UI-1
information architecture** (`ansich/docs/ansich-ui-information-architecture.md`):
Task detail leads with a sticky hero (human-recognizable `actor · source_kind ·
short-id`, control + duration + highest-priority signal; full UUID/source/resolver
fold into Technical details) and a three-block diagnostic strip (current activity /
why attention / impact) whose primary signal is a presentation selection over
existing backend-resolved beliefs (`selectPrimarySignal`, not a new authority rule —
the versioned resolver is UI-2). The seven flat tabs collapse into four
question-oriented entry points with URL view state (`?view=summary|decision|resources|evidence`):
Summary (diagnostic strip + Task tree), Decision trace (logical Steps), Resources &
safety (Budgets + Scopes & effects), and Evidence (timeline + context & lineage +
Agent release, all lazy/no-store). Projection health renders as a compact
`Data healthy · lag` line promoted to a page-level banner when the page's own
scope warrants it; the full metric wall lives in the `System details` drawer.
That scope is tiered: Operations keeps the global counts, while Task detail
counts only that Task's own failed jobs (a bounded `failed-jobs?task=` page,
rendered as `50+` when full) and its own lost ranges — an unattributed range
(`task_id: null`) stays system-scoped and is never charged to a Task — so global
degradation caused by other Tasks no longer interrupts a Task page. A
system-level hard failure (`storage_available=false`, status failed/stopped) is
the exception and still appears there, explicitly labeled system-level, because
the Task's own numbers come from the same projection and must not be reported as
clean. A Task failed-job count that has not answered — pending, or failed with
no retry — is carried as `null`, not 0: unknown never promotes a banner or
counts into the badge, but it does replace the green completeness line with a
neutral "count unavailable" one. Against a dismissal snapshot it compares
asymmetrically: a count that goes unknown is never a rise, but a snapshot taken
while the count was unknown acknowledged no count at all, so one that later
resolves with failures in it re-promotes the banner (resolving to zero does
not). The banner is dismissible: it hides entirely and leaves an amber `⚠ N`
button in the page title row that restores it, so the warning moves rather than
leaving the accessibility tree. The dismissed state (failed/lost counts plus
status) is kept per scope in `sessionStorage` (`core/ansich/health-dismissal.ts`,
system and each Task independent); a rising count or a worsening status
(healthy < recovering < degraded < failed/stopped) drops the record and
re-promotes the banner, a recovery a real count can vouch for clears it so the
next incident opens as a banner again (an unknown count clears nothing —
otherwise the pending window after a reload would discard the record), and a
hard failure renders no dismiss button at all. The collector reports seven
lifecycle states and the banner treats them in three groups: `recovering` is
attention (the incident is not over) and takes part in the worsen order above,
while `starting` and `shutting_down` are transient lifecycle phases — neither
raises attention on its own, and neither takes part in the worsen comparison in
either direction, the same posture as an unknown count. A phase excuses only the
status: a failed job, a lost range, or unavailable storage recorded during one
still raises the banner. A phase is equally not a clean bill of health, so
instead of the emerald completeness line it renders a fourth line state
(`phase`) in the same muted treatment as the unknown-count line, naming the
status word itself; it is dismissible by nobody and clears no dismissal record,
because acknowledging nothing is not a recovery. Persisted dismissal records
validate their status against the contract's own `ANSICH_HEALTH_STATUSES` list
rather than a second literal copy, so a record taken at any of the seven
survives a reload. Every metric label in that drawer has a keyboard-focusable
help trigger whose localized tooltip explains the metric's definition and diagnostic
meaning; failed-job help stays separate from the clickable failed-job value. UUIDs on
list rows and the hero downgrade to their leading
8-char segment (`AnsichShortId`), full value behind copy/tooltip. Alert detail is
ordered by action priority (summary → severity/workflow/active → impact → operator
actions → why-triggered evidence → observation timeline) with rule/version/config
hash/workflow history folded into Technical evidence. Deferred to UI-2+: the
Operations authoritative Attention Queue, aggregate `operations/overview` /
`diagnostic-summary` read models, the versioned primary-signal resolver, and the
graphical causal trace. Logical Steps fold
provider retries into attempts and render internal system operations separately;
each ToolCall renders an ordered four-stage accountability chain (Issued,
Authorization, Execution, Visible to model). Unknown authorization/execution is
shown explicitly, and parallel calls stay in model-issued `call_seq` order.
Context initially renders only ordered hashes/size/token inventory. It preserves
missing ordinals as explicit unknown gaps and labels incomplete snapshots; it
must never collapse a missing ContentBlock into an apparently shorter complete
request. If no Step has an effective snapshot while projection health reports
failed jobs, the Context tab renders an explicit projection-unavailable warning
instead of the ordinary no-context empty state; the wording remains cautious
because projection health is process-wide. Projection health also renders queue
count/byte capacity and both high-watermarks, plus snapshot
request/item/incomplete/missing counters, unreported global loss ranges (loss
belonging to no single Task, which nothing could write back into the Observation
stream), a writer block (consecutive failures, backoff until, rows in flight,
isolated drops), and a bounded per-producer table ordered by dropped count
(`topProducersByDropped`, top 8, remainder counted below the table, plus the
producer-ledger eviction count). Copy for those is deliberately literal: rows in
flight counts every outstanding row including a terminal flush write and is not
a writer-backlog gauge, isolated drops names dropped rows without diagnosing
whether the cause was a few unwritable rows or a longer outage, and account
evictions counts eviction events rather than distinct producers lost. When
`failed_jobs` is non-zero the metric is clickable and opens `AnsichFailedJobsDialog`, which lists currently-failing projection/assessor jobs (Task-scoped on the Task detail page, global with per-Task retry grouping on the Operations page) and lazily fetches each job's full attempt-error history on expand. Raw ContentBlock bodies are fetched
lazily after an explicit admin click and must never be placed in the polling
response or TanStack query cache pre-emptively. Tool raw and model-visible
payloads use separate `no-store` API calls and separate buttons; never collapse
them into one generic result field.

Phase 6 adds a separately polled, cursor-paged “Alerts” lens to Operations.
The list remains metadata-only; selecting an episode lazily fetches its source
Belief, assessor/rule version and config hash, ordered Observation evidence,
current Task Beliefs, workflow history, and available actions. Presentation
must distinguish exact/absolute runaway evidence from Tool-frequency
operational signals, heartbeat liveness rules, and shadow observation-only
policy. Task Overview renders the backend-resolved current behavior Belief and
never derives semantic state in the browser. Acknowledge/dismiss use the
server's workflow version, while interrupt/rollback require an explicit
confirmation and a per-attempt idempotency key. Pending actions disable
duplicates; 409/failure paths refetch and preserve the evidence dialog, never
show optimistic success. Interrupt copy says that execution stops while the
current checkpoint is retained and must not call it pause; rollback copy names
the pre-run checkpoint restore.
The UI advertises only Alert types with live producers: budget
warning/exceeded, exact repetition, Tool frequency, heartbeat missing, and long
dwell; Phase 7 also exposes provider `configuration_drift`.
P11-B adds the two process-subject types, `projection_failure` and
`observability_degradation`, whose producers and host-`Scope` subject mapping now
exist; they carry real labels and a category, closing the interim window in which
the unfiltered list already returned them under a blank type. Both are
Scope-subject, so the Alert detail dialog offers no Task link for them — the
subject decision is an exhaustive switch (`isTaskSubjectAlert`) precisely so a
later type has to declare what it subjects instead of inheriting a link to a page
that does not exist.

Operations gains a fourth lens, "Observability" (`AnsichObservabilityHealthPanel`),
reading `GET /api/ansich/health` through its own query — the one Ansich route that
still answers while SQL storage is down. Its boundary with the System details
drawer is a hard one and is written into both components' docstrings: the drawer
is this worker's process/collection wall (queue, writer, producer ledger, its own
advisory failed-job count), while the panel is the store's answer read live across
every worker (per-projector job buckets, the continuity mark, the authoritative
failed-job count). Under several Gateway workers the two legitimately disagree, so
they are never merged and never share a label — "Failed jobs (all workers)" versus
"Failed jobs seen here". The `database` block's `status` gates every other field:
`unreachable` renders an explicit banner and every number as `—`, never as zero,
and the presentation selector discards numbers such a block should not have
carried; the process-side numbers stay visible underneath, mirroring the endpoint.
`retry` is its own column beside `pending` because a re-armed job is work still
owed, and `complete_through` is labelled "settled through" / 「已结算至」 and never
as progress — it is a continuity mark that one stuck job holds down however far
past it the projectors have otherwise run, so it reads lower than the old
per-worker watermark whenever anything is outstanding. The store-wide mark shown is
the lowest per-projector mark, and unknown when any projector's own is unknown.
The headline badge has **three** states, not two (`databaseHealthBadge`): a
reachable store with durably failed jobs is `attention` in the destructive tone,
never a green "reachable" — connecting successfully is not a clean bill of health,
and that is the very condition `projection_failure` alerts on; `unreadable` keeps
its own amber tone because nothing known is a different claim from something
failing.

**Known issue on that page (pre-existing, not introduced by the lens, and
deliberately left alone):** the Operations page renders the selected lens's query
error *instead of* the whole `<Tabs>` block — including the `TabsList` — so while
the selected lens's fetch is failing there is no tab bar to switch away with, and
the page only comes back when the poll recovers. The health query is simply the
fourth endpoint that can now trigger it. Fixing it means rendering the error
*inside* the tab panel and keeping the trigger row mounted, which is a change to
shared page structure rather than to this lens.

Ansich display formatting lives in `core/ansich/presentation.ts` and is shared, not
per-component: `formatAnsichLag` is the one lag rendering for the health line, the
drawer and the panel (sub-second in `ms`, past a second in `s` — two views one
click apart must not disagree about the same `lag_ms`); `formatAnsichCount` groups
a quantity using the **app** locale passed in, the way `formatAnsichTimestamp`
already takes it, never a bare `toLocaleString()` that would follow the browser's;
and `formatAnsichSequence` renders an ingest-sequence mark ungrouped, because a
position in the stream gets compared against the raw `ingest_seq` in a log line.
`AnsichMetricHelp` is the single help-trigger component behind every metric label.

Phase 7's Agent Release tab reads the Task's immutable `executed_by` binding
separately from the normal Task polling query. It renders component hashes,
sanitized effective model/policy/build values, structured Tool schemas, and the
backend-resolved provider-drift Belief/evidence. The normal detail response may
show only the controlled prompt preview; the full manifest is never prefetched
or placed in the release query cache. Release comparison always consumes the
backend typed diff and keeps Tool added/removed/schema/description/source changes
distinct. The release header's quality and distribution badges remain hardcoded
`unassessed` and `unavailable` — the backend still pins `summary.quality_status`
to that literal and no operational aggregation exists — and must be requalified
only when those aggregates land, not from the Phase 10 comparison below.
Phase 4 keeps lineage lazy as well: each ContentBlock row loads its local
backward provenance, forward descendants, or possible exposures only after the
admin selects that action. The graph view must retain depth, transform labels,
truncation, and unknown gaps, and must ship an equivalent table fallback.
Forward results are always labeled “possible exposure” and never imply model
attention or causality. The Context & Lineage tab discovers all compression
summaries through the Task-scoped cursor-paged API, independently of the bounded
timeline, and offers explicit pagination. It fetches full compression detail
only on demand and renders typed `source`/`preserved`/`removed` memberships in
strict disposition/ordinal order. Snapshot, compression, and lineage polling
must never fetch raw bodies.

Phase 10 adds a fifth question-oriented entry point to Task detail,
`?view=evaluations`, rendered by `AnsichEvaluationsPanel`. It leads with the
backend's five quality dimensions, always all five: an `unassessed` dimension
gets the same neutral muted treatment as `unknown` and may never borrow the pass
or fail colour, because nothing assessed is not a pass and a completed Task
never implies one. Each dimension shows the selected assertion's assessor,
authority/fidelity, `as_of`, resolver, evidence Observation ids, and a conflict
badge whenever losing assertions were retained — the browser selects nothing and
derives no verdict of its own. Below it, the
Recorded evaluations list is metadata only; `expected`/`actual`/`rationale` are
bodies and follow the same rule as raw Tool and ContentBlock payloads — loaded
one Observation at a time through the `no-store` payload route after an explicit
expand click, never polled, prefetched, or written into the query cache. Release
comparison gains a separate Quality card (`AnsichReleaseQualitySection`) kept
visually apart from the structural diff: each `(dimension, cohort)` row renders
exactly one of three distinct states — an observed delta with its sample counts,
a muted `not_comparable` with the localized reason (muted, never the error
colour: declining to compare is not a failure), or a neutral unassessed marker
when the pair was comparable in principle but produced no delta — which is not
the claim that there is no difference.
A cohort text box commits on Enter or blur rather than per keystroke, a blank
box means every cohort, and the empty cohort key stays reachable only as an
explicit per-row label. Delta copy is observed-only and states its orientation
(the selected release minus this Task's release); scale polarity is shown only
when both coverage cells declare it, and the sign alone never implies better.
The whole card is absent, not empty, when the response carries no `quality`
block.

Composer drafts are tab-scoped browser state. `core/threads/composer-draft.ts` stores only text plus the selected slash-skill name in `sessionStorage`, keyed by user, agent, and logical conversation scope. New-chat pages pass the stable scope `"new"` because their runtime `threadId` is a fresh UUID on every reload; established conversations use their real thread ID. `InputBox` waits for enabled skills before restoring a skill chip, degrades a missing/disabled skill back to editable slash text, and clears the stored draft through `SendMessageOptions.onSent` only after the send passes the in-flight guard. Attachments, sidecar quotes, voice state, and polish undo state are not persisted.

Auth UI note: the login page's "keep me signed in" option submits only `remember_me` to the Gateway and may persist only the email address through `core/auth/remember-login.ts`. Passwords and tokens must never be stored in frontend storage; the `HttpOnly access_token` and readable `csrf_token` cookies remain Gateway-owned.

`/goal` and `/compact` are built-in composer commands, not skill activations. `src/components/workspace/input-box.tsx` intercepts `/goal`, `/goal clear`, and `/goal <condition>` before normal chat submission, calling Gateway `GET/PUT/DELETE /api/threads/{thread_id}/goal`. Setting `/goal <condition>` also submits the condition text as the next user task so the agent starts running immediately; status and clear do not start a run. Goal and compact requests are tied to the current `threadId` with an `AbortController`, so switching threads or unmounting the composer aborts in-flight requests and stale responses cannot update the new thread's composer state. The chat pages render `GoalStatus` above the composer from `AgentThreadState.goal`, with local optimistic state until the next stream `values` update arrives. `/compact` calls `POST /api/threads/{thread_id}/compact` to summarize older active context while leaving the full visible chat history intact; it is skipped on new/empty threads and blocked server-side while a run is in flight.

Human input requests are a structured message protocol layered on normal chat history. The backend writes request payloads to `ToolMessage.artifact.human_input`, `src/core/messages/human-input.ts` owns the runtime validators/types, and `src/components/workspace/messages/human-input-card.tsx` renders the reusable card. `MessageList` owns answered/latest/pending state for visible cards, but derives answered responses from raw `thread.messages` because replies are hidden; pending cards clear when the hidden reply appears, when dispatch is dropped, or when a new `thread.error` reports an async stream failure. Page-level submit callbacks must send a normal human message and put `hide_from_ui: true` plus the response payload in the fourth `sendMessage(..., options)` argument as `options.additionalKwargs`; the third argument remains run context such as `{ agent_name }`. Composer entry points should disable normal bottom input while `hasOpenHumanInputRequest(...)` is true so users answer through the card and preserve response metadata.

Tool-calling AI messages can contain user-visible text as well as `tool_calls`. `core/messages/utils.ts` keeps these turns in an `assistant:processing` group, and `components/workspace/messages/message-group.tsx` must render the visible text as a processing step instead of treating the message as only tool metadata. This preserves provider text such as error explanations or "trying another approach" notes during tool-heavy runs.

### Key Patterns

- **Server Components by default**, `"use client"` only for interactive components
- **Thread hooks** (`useThreadStream`, `useSubmitThread`, `useThreads`) are the primary API interface
- **Thread routes** — construct Web UI chat paths through `core/threads/utils.ts::pathOfThread()`, which percent-encodes both custom agent names and thread IDs before inserting them into route segments
- **LangGraph client** is a singleton obtained via `getAPIClient()` in `core/api/`
- **Streaming Markdown rendering** is owned by `core/streamdown`: Streamdown's `animated` / `isAnimating` API handles incremental word animation, while the shared `streamdownRenderingPlugins` config registers the named code-highlighting and Mermaid plugins required by Streamdown 2.5. Keep wrappers and derived configs wired to that shared object; do not reintroduce a rehype plugin that wraps every word, because reparsing a growing block remounts old words and replays their animation.
- **Environment validation** uses `@t3-oss/env-nextjs` with Zod schemas (`src/env.js`). Skip with `SKIP_ENV_VALIDATION=1`
- **Subtask step history and runtime metadata** (`core/tasks/`) — the subtask card shows a subagent's full step timeline (#3779): its assistant reasoning turns interleaved with the tools it ran. `Subtask.steps[]` is accumulated live from `task_running` events (appended via `mergeSteps`, not overwritten) and backfilled on expand for historical runs by `fetchSubtaskSteps`, which pages the events endpoint scoped to one task (GET `/runs/{runId}/events?event_types=subagent.step&task_id=…&after_seq=…`) until a short page, so the run-wide limit can't truncate the timeline. `task_started` carries the effective `model_name`; `task_running` carries a cumulative usage snapshot after each completed LLM call. `core/tasks/lifecycle.ts` normalizes these additive events, and `computeNextSubtask` keeps the largest cumulative total so replayed or late SSE frames cannot double-count or roll the folded card backward. Terminal ToolMessage metadata (`subagent_model_name` / `subagent_token_usage`) restores the same values from normal history after reload; no per-card event fetch is needed. `core/tasks/steps.ts` is the pure step model: `messageToStep` (live), `eventsToSteps` (reload), `mergeSteps` (dedup by `message_index`), and `stepsForDisplay` (what the card renders — keeps tool steps + AI steps with text, drops the trailing final-answer AI step when completed since it's shown as `result`). `core/tasks/context.tsx`'s `useUpdateSubtask` applies updates against a `tasksRef` mirroring the latest state (not a closure snapshot), so a late-resolving `fetchSubtaskSteps` backfill merges into current state instead of clobbering SSE steps or sibling subtasks that arrived meanwhile. The owning `run_id` is carried onto history content messages in `buildVisibleHistoryMessages` so the card can resolve the events endpoint.

### Interaction Ownership

- `src/app/workspace/chats/[thread_id]/page.tsx` owns composer busy-state wiring.
- `src/app/workspace/chats/[thread_id]/page.tsx` owns branch-from-turn submission and navigation; sidecar `MessageList` instances do not receive the branch action.
- `src/app/workspace/chats/[thread_id]/page.tsx` gates the Workspace Browser trigger and browser right panel on `/api/features -> browser_control.enabled`; default/failed feature discovery hides the browser control so optional backend installs do not show a dead Live socket.
- `src/app/workspace/chats/[thread_id]/page.tsx` and `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` own active-goal display state for their composer overlays.
- `src/components/workspace/messages/message-list.tsx` owns human-input card answered/latest/pending gating; entry pages only translate a submitted card response into `sendMessage` calls.
- `src/components/workspace/browser-view/browser-view-panel.tsx` forwards each physical pointer click as one `click` input; do not also emit `down`/`up` for the same gesture because the remote Playwright click would run twice.
- `src/core/threads/hooks.ts` owns pre-submit upload state and thread submission.

## Code Style

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

## Environment

Backend API URLs are optional; an nginx proxy is used by default:

```
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:8001/api
```

Leave these unset for the standard `make dev` / Docker flow, where nginx serves the public `/api/langgraph/*` prefix and rewrites it to Gateway's native `/api/*` routes.

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Core Concepts](https://js.langchain.com/docs/concepts)
- [TanStack Query Documentation](https://tanstack.com/query/latest)
- [Next.js App Router](https://nextjs.org/docs/app)

## Contributing

When adding features:

1. Follow the established `src/` structure
2. Add TypeScript types and proper error handling
3. Write unit tests under `tests/unit/` (`pnpm test`) and E2E tests under `tests/e2e/` (`pnpm test:e2e`)
4. Run `pnpm check` before committing
5. Update this `AGENTS.md` when architecture, commands, or conventions change
