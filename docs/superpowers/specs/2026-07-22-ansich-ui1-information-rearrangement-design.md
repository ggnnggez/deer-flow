# Ansich UI-1: Frontend Information Rearrangement

- **Date**: 2026-07-22
- **Spec source**: `ansich/docs/ansich-ui-information-architecture.md` (§11 UI-1)
- **Scope**: UI-1 only — pure frontend reorganization, reuse existing APIs, **no backend changes**, no extra per-Task query for a first screen.
- **Branch**: `ansich-dev`
- **Status**: approved (scope confirmed by user), ready for plan

## Goal

Reorganize the Ansich admin observability UI from a flat "projection table browser"
into a progressive-disclosure information architecture, following the existing DeerFlow
visual vocabulary (shadcn `Badge/Card/Tabs/Dialog/Drawer`, `border-{color}-500/40 bg/10
text-700 dark:text-300` semantic colors, `font-mono` IDs, `tabular-nums`, `cn()`, i18n
`t.ansich.*`, `WorkspaceContainer`). Do **not** introduce a new visual system.

## Principles

- Progressive disclosure L0–L3: default show L1; L3 (UUID/hash/resolver/payload) reached
  only via explicit `Technical evidence` / `View raw payload` / `Lineage`.
- Downgrade, never delete: short IDs by default, full value behind Copy/Technical details;
  hashes hidden until comparison is needed.
- Five evidence states stay distinct and never collapse to "healthy": `unknown`,
  `partial`, `degraded`, `unconfigured`, `none observed`. Empty arrays/missing rows must
  not render as healthy/no-effect.
- Color always pairs with text + icon; at most one red primary signal on a first screen.

## Scope (UI-1 deliverables)

### 1. Task Detail restructure (`app/workspace/ansich/tasks/[task_id]/page.tsx`)

- **Sticky hero** (`task-hero.tsx`): `actor · source_kind · shortId` + control + duration +
  child count + highest-priority open signal + operator action. Full UUID/source_id/
  thread/owner/watermark move into a `[Technical details]` disclosure.
- **Diagnostic strip** (`task-diagnostic-strip.tsx`): three semantic blocks —
  - *Current activity*: current Step/Tool + dwell (from control belief).
  - *Why attention*: pick ONE primary signal from **existing backend-resolved signals** by
    a fixed priority (behavior belief runaway > budget exceeded > scope violation >
    observability degraded > else `Insufficient evidence`). This is a **presentation
    selection**, not a new authority rule (UI-2 replaces it with a backend resolver).
  - *Impact*: child count (tree) + resource headline (usage).
  - No evidence → `Insufficient evidence`; never a green healthy placeholder.
- **7 tabs → 4 question-oriented entry points**, reusing existing panels:
  | Entry | Composed from |
  | --- | --- |
  | Summary | hero + diagnostic strip + Task tree summary + resource headline + latest trace summary |
  | Decision trace | Steps two-level accordion (embedded Context/Authorization/Effect summaries) |
  | Resources & safety | Budgets + Scopes&Effects **merged**, exception-first ordering, local/inclusive usage |
  | Evidence | Observation Timeline + Context&Lineage + Compression + Agent Release + projection diagnostics + on-demand raw/visible payload |
- Primary view state written to URL query (`?view=decision&step=7&evidence=authorization`)
  for stable deep links.

### 2. Step two-level accordion (`progressive-step-card.tsx`, refactor `step-explorer.tsx`)

- Collapsed: one-line summary (`Step 7 · Acting · 1.8s / Context 23 items → selected bash
  → returned / 1 ToolCall · effect coverage partial`).
- First expand: LLM attempts + ToolCall accountability chain + Authorization/Effect
  summary + context completeness + raw/visible availability.
- Second expand `Technical evidence`: step/tool/attempt UUIDs, observation IDs,
  args/content/policy/config hashes, producer/resolver versions, causation/lineage edges,
  payload access.

### 3. Alert Detail action-priority reorder (`alert-panel.tsx` detail dialog)

Reorder detail to: one-line event summary → severity/workflow/active → impact + current
activity → operator actions → "why triggered" evidence → observation timeline →
rule/version/config-hash/workflow-history (folded). List, workflow-version and
idempotency-key behavior unchanged. Interrupt copy = stop + retain checkpoint (never
"pause").

### 4. Projection Health compact + drawer + UUID downgrade

- `projection-health.tsx` → compact status line (`Data healthy · lag 1.2s [System
  details]`) + `system-health-drawer.tsx` (full queue/watermarks/snapshot/failed jobs).
  When degraded/failed/lost-range/storage-unavailable, promote to a page-level banner that
  cannot be drowned out by ordinary task cards.
- `short-id.tsx` primitive: short 8-char id + Copy button + tooltip full value; used
  wherever a UUID appears on a first screen.
- Operations page this cycle receives only this item (projection compact + UUID
  downgrade); its active/history/alerts tab structure is unchanged.

### 5. Shared primitives / pure logic

- `technical-evidence.tsx`: collapsible L3 wrapper (UUIDs/hashes/resolver/producer).
- `presentation.ts` additions: `selectPrimarySignal(...)` (fixed-priority selection over
  existing beliefs/health), `classifyEvidenceQuality(...)` (five distinct states).

## Component plan

New: `task-hero.tsx`, `task-diagnostic-strip.tsx`, `progressive-step-card.tsx`,
`resource-safety-panel.tsx`, `technical-evidence.tsx`, `system-health-drawer.tsx`,
`short-id.tsx`.

Refactor: `projection-health.tsx`, `step-explorer.tsx`, `scope-effects-panel.tsx` +
`budget-panel.tsx` (→ `resource-safety-panel.tsx`), `alert-panel.tsx`, the two page files.

i18n: add keys to `core/i18n/locales/en-US.ts`, `zh-CN.ts`, `types.ts`.

Tests: unit tests for `presentation.ts` pure functions (primary-signal priority,
evidence-quality five states, short-id formatting); component behavior tests (accordion
two-level expand, drawer, alert detail order). `pnpm check` must pass.

## Non-goals (deferred to UI-2/3/4)

- Operations authoritative Attention Queue / `operations/overview` / `diagnostic-summary`
  / versioned primary-signal resolver / Alert-subject→Task aggregation (**UI-2 backend**).
- Horizontal graphical Causal Trace + full deep-link node targeting (**UI-3**).
- High-concurrency real-data density tuning + visual-regression/E2E acceptance (**UI-4**).
- No relaxation of Ansich admin access control. No raw prompt/credential/host-path in any
  summary view. No browser-side Alert/Belief authority rules.

## Acceptance (UI-1 subset of IA §12)

- First screen shows no full UUID, hash, or JSON.
- One click from a task row to Task Summary; two clicks to the triggering Step/ToolCall.
- Raw payload fires no network request before an explicit click.
- Projection healthy → no full metric wall; projection degraded → page-level notice not
  drowned by task cards.
- `unknown/partial/degraded` never render as healthy.
