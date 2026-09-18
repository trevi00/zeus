# Report + background 001 — Interface lane note (보고서 story)

Worker: Claude, isolated Zeus worker (Linux, restricted), 2026-09-18. Base
f067bb633831363348ad3108b6382a580cb723f8 (from the task envelope; git reads were not available in
the worker sandbox, so the revision was not confirmed by the worker). Frame: `SPEC.md` in this
directory, section "Interface lane" and the acceptance matrix, followed as fixed. Backend lane not
touched. Owner keeps npm typecheck/lint/build, browser acceptance (390px, dark, print), full suite,
packaged assets and CI.

Scope touched: `frontend/monitor/src/lib/report.ts`, `frontend/monitor/src/views/report.tsx`, new
`frontend/monitor/src/components/report-story.tsx`,
`frontend/monitor/src/components/report-visual-summary.tsx` (heading + comment only),
`frontend/monitor/src/index.css` (two print rules), this note. No backend, HTTP, test, dependency,
packaged asset, `snapshot.ts`, `use-snapshot.ts`, `tones.ts`, `fleet.tsx` or `App.tsx` change.

## Authority searched and disposition

- Searched `frontend/monitor/src` for `fleet`, `readFleet`, `zeus-observatory-report`,
  `ReportVisualSummary`; searched `tests/` for `frontend/monitor` and `monitor/src` (no hit); grep
  over the checkout for the report schema string hit only the frontend, docs and the packaged
  bundle. No Python consumer of the report JSON exists in this checkout (same finding as
  observatory-001 IMPLEMENTATION.md), so the schema bump below breaks no reader that was found.
  An empty search is not proof: an out-of-repo consumer of the JSON download is unknown.
- Reused: `Snapshot.sources.fleet`, `FLEET_SCHEMA`, `FleetJob/FleetLane/FleetRegistered/FleetData`,
  `fleetFreshness` (accepted 20s / future-5s rules) from `snapshot.ts`; `StatusBadge`, shadcn
  `Card`, Lucide icons, `freshnessTone`, the node/arrow flow pattern and truth vocabulary of
  `report-visual-summary.tsx` and `views/fleet.tsx`; the pinned-report contract of `report.ts`
  (build once at view entry or regenerate, same object for screen, print and JSON).
- Mirrored, not shared (recorded incompatibility): the fleet narrowing rules (`readFleet`) and the
  dependency verdict (`dependencyState`) are view-local, unexported functions of `views/fleet.tsx`,
  which is outside the allowed paths. `report.ts` now carries `parseFleet` and `dependencyStateOf`
  with the same rules and the same INV-FLEET-001 labels. Follow-up for the owner, not done here:
  move both into `snapshot.ts` (or a `lib/fleet.ts`) and import them from both the 팀 작업 view and
  the report so one authority remains. Until then the two copies must be changed together.
- Justified new: `Story`/`ReportFleet` types and `buildStory`/`captureFleet` in `report.ts`
  (capture-time derivation, same place as `buildExplanation`), and the `ReportStory` component.
  The before/after text is a fixed constant describing this screen's layout change only.

## Contract (`report.ts`)

- Schema `zeus-observatory-report.v3` -> `zeus-observatory-report.v4`. Every v3 field is unchanged
  in name, type and derivation; two fields are added:
  - `fleet: ReportFleet` — one capture of `sources.fleet` at build time: `state`
    (`missing | unavailable | invalid_data | unregistered | registered`), `detail`, envelope
    `status`/`error`, `observed_at`, `freshness` + `freshness_reason` + `age_seconds` (fleet
    observation age at capture, independent of any job timestamp), `sample {limit:100, count,
    truncated}` and `data` (a new object built by `parseFleet`, detached from the live snapshot;
    `null` unless registered).
  - `story: Story` — pure function of `fleet`: four conceptual stages, `state`/`state_note`,
    `fleet_id`, `control` (admission, active lanes / `max_parallel`, lanes total, active jobs
    outside the sample, declared budget ceilings, sample reservation/settlement sums flagged
    `partial` with the count of jobs whose calls were null, fixed policy lines), `teams` (each with
    lanes and their `active_job` + `active_in_sample`, and the team's `StoryJob`s), `outcomes`
    (per-verdict counts), `remaining` lines, `caveats`, and the `comparison` block.
- `StoryJob` carries only stored facts: id, `short_id` (first 20 chars), team, lane, operation id,
  `goal.criterion`/`goal.path`, raw `status`, `verdict` (the seven INV-FLEET-001 states or
  `undefined` for anything else, rendered raw), label/meaning, `reason_code`, `calls`,
  dependencies with each prerequisite's sampled status or `sampled:false`, dependency verdict,
  a `remaining` sentence, `created_at`, `updated_at`. Empty strings from the wire become `null`.
- Not derived anywhere: per-stage timestamps, reviewer findings, patches, merge/deploy state,
  remaining money or calls, machine call totals, completion estimates. `SOURCE_NAMES`,
  `sources`, `explanation`, `next_actions`, `caveats` of the v3 body do not see fleet.

## View (`report.tsx`, `report-story.tsx`)

Order on screen and in print: header/notices -> `ReportStory` -> `ReportVisualSummary` (now headed
"집계 요약 (샘플)") -> the existing disclosures (쉬운 설명, 범위·시각·완전성, 건수, 운영 결과, 치명·오류,
다음 조치). The story is never inside a `<details>`. The 범위와 시각 card gains one row showing the
fleet capture state/freshness/observed time next to the four fixed sources.

`ReportStory` reads `report.story` and `report.fleet` only. Blocks, top to bottom:

1. Header card: title "이야기로 보는 팀 작업 · 무엇을 하려는가 → 어느 팀이 수행했는가 → 어떤 판정인가 →
   무엇이 남았는가"; badges for fleet id + freshness (or the unknown/empty state), "개념 단계 ·
   단계별 측정 시각 없음 · 생성·마지막 기록 시각만 실제 값"; observed time "캡처 시점에 고정 · 다른
   출처와 독립". Four stage boxes joined by arrows (vertical below `md`, horizontal at `md`).
   When the state is not `registered`, the state notice renders in place under the stages.
2. 유한 운영 띠 (registered only): admission (열림/일시 정지), 활성 레인 / 동시 실행 상한 with lanes
   total and out-of-sample active count, 호출 상한 host/total labelled "선언된 호출 수 상한 · 남은
   호출·금액·실제 지출 아님 · 기계 장부 없음", 표본 예약/정산 합계 labelled "기계 전체 아님" and
   "부분 합계" when any job had null calls (확인 불가 when all were null), 표본 count/truncation
   with the 100 bound, fleet observed time and capture-relative age "하트비트 아님". Policy badges:
   explicit jobs only / owner grants next budget / ceilings are not a balance.
3. 팀별 작업 흐름 (registered only): one swimlane per team (from lanes and jobs; jobs without a
   team fall under "팀 없음"), lane badges with `active_job` (lock, unknown tone when the active job
   is outside the sample, "(표본 밖)"), then each job as four connected nodes:
   목표 (criterion, goal path, operation id; badge = short id, full id on hover) -> 팀 · 레인
   (created, last record "생존 신호 아님", "단계별 시각 · 기록 없음") -> 판정 (status badge in its
   tone, meaning, reason, calls reserved/settled with 확인 불가 for null) -> 남은 것 (remaining
   sentence; for jobs with dependencies the dependency verdict badge and each prerequisite's
   sampled status or "표본 밖 · 알 수 없음"). Empty team/sample states have their own copy.
4. 결과 (표본) counts per verdict with the remaining rule for each, and 무엇이 남았는가 lines
   (unknown -> owner reconciliation; failed/rejected/exhausted -> reason recorded, owner decides;
   dispatching -> no end record; queued -> admission/dependency; accepted -> candidate accepted,
   merge/deploy unknown). Non-registered states show 확인 불가 (0건 아님) or 비어 있음 in place.
5. 이 이야기의 한계: stale/invalid observation, sample truncation, out-of-sample active jobs,
   jobs with unknown calls, out-of-sample prerequisites, and always the line that per-stage times,
   review findings, patches, merge/deploy facts are absent from the source.
6. 이 보고서 화면의 이전과 현재: two boxes joined by an arrow, badged "UI 설계 비교 · 측정된 운영
   개선 아님 · 소스 변경 요약 아님" with the note that no measurement was requested or provided.

State matrix (evaluated in `captureFleet`, in this order):

| Input | `fleet.state` | Shown in place |
|---|---|---|
| no snapshot | `missing` | 확인 불가 · 정상 응답 없음 |
| snapshot without `sources.fleet` | `missing` | 확인 불가 · 이전 계약의 수집기 · 비어 있음 아님 |
| envelope `status != "ok"` | `unavailable` | 확인 불가 with status/error and observed time |
| `status ok`, body off contract | `invalid_data` | 확인 불가 with the parse reason and expected schema |
| `registered:false` | `unregistered` | 비어 있음 · 확인 불가 아님; outcomes show 0건 |
| registered, observation stale/invalid | `registered` | board rendered; header badge and caveat say 현재 아님 |
| registered, fresh | `registered` | board rendered |

Mobile/dark/print: every grid is one column below `md` (job rows) or `sm` (control strip); ids and
labels use `break-words`/`break-all`; only existing tokens are used; the story cards are outside
the disclosures so they print; `index.css` adds `break-inside: avoid` per job row and
`print-color-adjust: exact` for node borders. Not verified in a browser here.

## Acceptance matrix mapping (UI part only)

- Normal (finite fleet, two jobs): each job renders its actual criterion, short id, team/lane,
  status, reason, calls, dependencies and remaining sentence; the control strip shows the declared
  ceilings and the two-job sample. Reachable from a registered envelope; not executed here.
- Failure: rejected/failed/exhausted keep their reason and "소유자 다음 결정"; report refusal
  (collector failure, off-contract body) stays 확인 불가 in place, never a blank or green board.
- Unknown: missing source, stale/invalid time, truncated sample and out-of-sample dependencies are
  labelled and never counted as zero or as met; `unknown` jobs demand owner reconciliation.
- Before/after performance: none measured, none shown; the comparison card says so.
- No runtime request, model call or control exists in the component or the builders.

## Verification

Run here (restricted worker; no `node_modules`, no npm, as assigned):

- `python -m ruff check .` — passed ("All checks passed!"). It does not touch TypeScript.

Not run by this worker and owed to the owner: `npm run typecheck`, `npm run lint`,
`npm run build`, browser acceptance at 390px, dark theme and print/PDF, the JSON download, the
full pytest suite, and the real collector path with a registered fleet. Lucide names newly used
(`Target`, `Flag`, `ArrowLeftRight`, `Workflow`, `Pause`, `Layers`, `Lock`, `CircleHelp`,
`ShieldCheck`, `Users`, `AlertTriangle`, `ArrowDown`, `ArrowRight`) were not checked against the
installed package. No frontend test harness exists in this checkout, so no synthetic fixture was
added; the seven capture states are reachable purely from the envelope contents and the owner can
exercise them by serving a snapshot with `sources.fleet` set to each shape. These are explicitly
not production executions.
