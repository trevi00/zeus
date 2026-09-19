# Local operations desk 001 — Part A note (UI only)

Worker: Claude, isolated Zeus worker (Linux, restricted), 2026-09-19. Base revision from the task
envelope: `340ba5c3580ed1c76bf72fb30887c50bbf92e4cb`; the SPEC header names base
`e67842a10c7400fc63a866b83391c672e39f53b9`. Git was not readable in this sandbox (`git status`
refused with "dubious ownership" and the follow-up command was denied by the tool policy), so
neither revision was confirmed by the worker and the difference between the two is unresolved here.
Frame: `SPEC.md` in this directory, section "Part A — first actual Claude assignment (UI only)",
followed as fixed. Parts B and C were not started: no backend, HTTP adapter, session, dependency,
lockfile or packaged asset was touched.

Scope touched: new `frontend/monitor/src/lib/accounting.ts`; `frontend/monitor/src/lib/snapshot.ts`,
`frontend/monitor/src/lib/report.ts`, `frontend/monitor/src/views/fleet.tsx`,
`frontend/monitor/src/views/overview.tsx`, `frontend/monitor/src/views/report.tsx`,
`frontend/monitor/src/components/report-story.tsx`,
`frontend/monitor/src/components/report-visual-summary.tsx`, and this note. Allowed but not edited:
`frontend/monitor/src/components/report-explainer.tsx` — it renders `report.explanation` only, and
the corrected guide/summary/caveat lines it shows are produced in `report.ts`, so no change there
was needed. No backend, test, CSS, `use-snapshot.ts`, `tones.ts`, `App.tsx` or asset change.

## Producer → consumer trace (read before editing)

- Producer: `src/codex_harness/domain/fleet.py` `projection()` (`urn:zeus:fleet-status:1`) emits, for
  a registered fleet, `budget: dict(config["budget"])` and `accounting_mode:
  accounting_mode(config["budget"])`.
- Authority for the mode: `src/codex_harness/domain/usage_policy.py`. `validate_budget` canonicalises
  to `{per_host, total}` for `finite` (no `mode` key — the legacy shape, digest-preserving) and to
  `{per_host, total, mode: "subscription"}` for subscription. `accounting_mode` refuses anything
  else rather than guessing. In subscription mode the two numbers are retained migration metadata:
  `headroom()` returns `remaining: None` and the lifetime count never refuses a start, while every
  call is still reserved and recorded.
- Transport: `src/codex_harness/application/fleet.py` `Fleet.status()` →
  `src/codex_harness/adapters/monitoring.py` `fleet_facts()` → `sources.fleet` envelope of
  `/api/status`.
- Consumers before this change: `readFleet` in `views/fleet.tsx` and `parseFleet` in `lib/report.ts`
  both validated `budget.per_host`/`budget.total` and **dropped** `budget.mode` and
  `accounting_mode`, so a subscription fleet was drawn as an active `per_host / total` call ceiling
  in the live 팀 작업 strip, in the pinned report control strip and in the report JSON.
- Pending terminations: `adapters/monitoring_observations.py` sums statuses
  `('pending_reconciliation', 'unconfirmed')` into `observations.terminations.pending`. What that
  blocks is in `application/execution_recovery.py` `_reconciled()`: recovery of a task is refused
  while termination records **with that task's `task_id`** are pending. That is the evidence for
  replacing the global "재실행 차단" wording with the affected-execution scope; no global execution
  block was found anywhere in the path.

## Authority searched and disposition

- Searched: `accounting_mode` over `src/`, `fleet`/`projection` over `src/codex_harness/adapters`,
  `budget|상한` and `미확정 종료|재실행 차단` over `frontend/monitor/src`, `zeus-observatory-report`
  over the checkout. No Python or test consumer of the report JSON exists in this checkout; the only
  other hit is the packaged bundle `src/codex_harness/resources/observatory/assets/index-*.js`,
  which is a compiled asset and was deliberately left stale (owner rebuilds). An empty search is not
  proof: an out-of-repo reader of the JSON download remains unknown.
- Reused: `usage_policy` semantics (not copied into the UI as numbers), the existing snapshot,
  freshness, pinned-report and truth-vocabulary contracts, shadcn `Card`/`Alert`/`StatusBadge`,
  Lucide icons already imported in this app (`ScrollText` was chosen over `History` because
  `node_modules` is absent here and only icons already used in this repo could be confirmed).
- Justified new: `lib/accounting.ts` — one interpretation shared by both decoders. It imports only
  `type Tone`, so `snapshot.ts` can import its `Accounting` type without a runtime cycle.
- Known duplication kept (recorded by report-background-001 UI.md and not resolved here): the fleet
  narrowing itself still exists twice (`readFleet`, `parseFleet`). This change makes the mode the
  one part they share by calling the same function. Follow-up for the owner, unchanged: move the
  whole narrowing into `snapshot.ts`/`lib/fleet.ts`. Until then the two copies change together.

## Accounting interpretation (`lib/accounting.ts`)

`interpretAccounting(accounting_mode, budget.mode)` — `undefined` means the field was absent:

| `accounting_mode` | `budget.mode` | result | basis |
|---|---|---|---|
| absent | absent | `finite` | `legacy_absent` (an absent legacy mode is the finite shape) |
| absent | `finite` / `subscription` | that mode | `budget_mode` (older collector without the top-level field) |
| `finite` | absent | `finite` | `top_level` (agrees with the legacy reading) |
| `subscription` | absent | **`unknown`** | `conflict` (the canonical subscription budget always carries the key) |
| equal values | equal values | that mode | `agreed` |
| different values | different values | **`unknown`** | `conflict` |
| any non-contract value (`null`, wrong type, unknown string) | — | **`unknown`** | `malformed` |

Never silently finite, and an unknown mode is never rendered as "no ceiling" either. An off-contract
mode does not invalidate the envelope: lanes, jobs and admission still render. The reading carries
`mode`, `basis`, the raw `declared` values, `ceiling_applies` (`true`/`false`/`null`), and the label
and captions used by both screens, so the JSON download can be audited.

UI wording: finite keeps `호출 수 상한 (호스트당 / 전체)` as the true ceiling; subscription shows
`구독 사용량 기록` with `호출 수 상한 미적용`, and the two numbers are captioned
`이관 메타데이터` — never a ceiling, provider allowance, free usage, remaining money or remaining
calls; unknown shows 확인 불가 with the wire statements that caused it. Migration numbers stay in
the JSON as `story.control.budget` / `fleet.data.budget` metadata next to the reading.

## Changes

- `lib/accounting.ts` (new): the rules above, `accountingDisplay` (one wording for both control
  strips) and `accountingTone`. Pure: no snapshot, clock, fetch or storage.
- `lib/snapshot.ts`: `FleetRegistered.accounting: Accounting` (type import only); `budget` still
  carries the two numbers alone.
- `views/fleet.tsx`: `readFleet` fills `accounting`; the third control card is now mode-aware; an
  unknown mode raises its own notice; the reading-guide footer is mode-aware; `검토 수락` and the
  검토 node say the owner's merge/deploy records are not connected; the `exhausted` label no longer
  asserts that a ceiling was reached, only that the state was recorded.
- `lib/report.ts`: schema `zeus-observatory-report.v4` → `v5` (additive, same convention as
  v2/v3/v4; every v4 field keeps its name, type and derivation). `parseFleet` fills `accounting`;
  `StoryControl.accounting` is captured with the report and the poll never rewrites it; the third
  policy line and the before/after "유한 운영 띠" text are mode-neutral; subscription/unknown modes
  add their own story caveat; a delivery caveat states that owner merge/deploy records are not
  connected and that their absence is not evidence of non-delivery. `nextActions` now prefixes every
  line with its own scope — `현재 상태` (explicit current conditions: pending terminations, local
  pending alerts, unreadable and pending local termination files, unacknowledged bytes),
  `기록 이력` (stored critical/error, alert, quarantine and operation records; outcome unresolved or
  unknown) or `확인 불가` (source, freshness, sample and uninterpretable-value limits). Nothing is
  deleted, no absent value becomes zero and no record is resolved by age. Two guide lines and one
  summary line were added for the history/current distinction and the termination scope.
- `views/report.tsx`: a `fleet 호출 회계` row (label, captioned numbers, basis and detail; distinct
  text for unregistered vs unreadable); `경보`/`격리` and the critical-event list are labelled
  기록 이력 with 결과 미확정; the termination row states the affected-execution scope; the
  next-actions card explains the three scopes; a null event outcome now reads 기록 없음 · 알 수 없음.
- `components/report-story.tsx`: control strip renamed `운영 한계 띠`, its budget cell replaced by
  the mode-aware accounting cell; accepted nodes and the outcome card say the delivery records are
  not connected.
- `components/report-visual-summary.tsx`: a `현재 상태 (명시적 기록)` row (pending terminations,
  local pending alerts, unreadable local termination files, observation freshness) above the
  aggregate, which is now labelled `집계 요약 (샘플 · 기록 이력)`; unreadable or absent sources stay
  확인 불가 rather than 0.
- `views/overview.tsx`: `우선 확인` split into `현재 상태 (명시적 기록)` and `기록 이력 (샘플)`. The
  pending-termination count is unchanged and still first; `운영자 조정 전까지 재실행 차단` is
  replaced by the affected-execution scope with its source statuses. History keeps every stored
  count and is labelled as neither resolved nor unresolved.

## Checks

- Run by the worker: `python -m ruff check .` from the repository root — `All checks passed!`
  (the backend is unchanged; this says nothing about the TypeScript).
- Not run, left to the owner as the SPEC directs: `npm run lint`, `npm run typecheck`,
  `npm run build` and any real browser observation (390px, dark, print, JSON download), plus the
  controlled finite / subscription / conflicting-mode browser fixtures. `node_modules` is not
  installed in this sandbox and npm is outside this worker's permission profile; no workaround
  command was attempted, so **the TypeScript in this change has not been compiled or type-checked by
  anyone yet**.
- Not run: the Python test suite (out of this assignment; no Python file changed).
- Not verified: git state and the base revision (see the header); the packaged observatory bundle
  still contains the pre-change v4 frontend until the owner rebuilds it.

## Open items for the owner

- Part A's acceptance rows "Normal A / Unknown A / History A" need the owner's browser fixtures; the
  `subscription` + absent `budget.mode` case is deliberately read as unknown (table above) and is
  the one reading an owner may want to overrule.
- The report JSON schema moved to `v5`; if an out-of-repo reader pins `v4`, that is an owner call.
- Delivery remains unconnected by design: Part B's explicit owner record is still required before
  any merge/deploy claim can appear on these screens.
