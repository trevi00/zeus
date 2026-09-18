# Fleet 001 — UI lane note (팀 작업 view)

Worker: Claude, isolated Zeus worker (Linux, restricted), 2026-09-18. Base
dd9c92b5e93460eda91d874de30de17f4ab0cf02. Frame: `SPEC.md` in this directory, section
"Monitoring wire contract" and "UI lane", followed as fixed. Owner keeps npm install/build/lint,
browser acceptance (390px and dark), full suite, real PG projection and CI.

Scope touched: `frontend/monitor/src/App.tsx`, `frontend/monitor/src/lib/snapshot.ts`, new
`frontend/monitor/src/views/fleet.tsx`, this note. No backend, HTTP, test, dependency, packaged
asset, `use-snapshot.ts`, `tones.ts`, `report.ts` or component file was touched.

## Authority searched and disposition

- Searched `frontend/monitor/src` and `src/codex_harness/adapters/monitoring*.py` for `fleet`:
  nothing exists yet. The backend lane owns the producer; this view is written against the SPEC
  shape only and treats a snapshot without `sources.fleet` as a valid older snapshot.
- Reused, not duplicated: `Envelope` and the accepted freshness rules (`snapshot.ts`, 20s window,
  future >5s and unparsable times never fresh), `StatusBadge`, `StatCard`, `KeyValue`, shadcn
  `Card`/`Alert`, `freshnessTone`, Lucide icons, the conceptual-flow node/arrow layout pattern of
  `report-visual-summary.tsx`, and the truth vocabulary of the other views (확인 불가 vs 비어 있음).
- `freshness()` was refactored into a shared private `envelopeFreshness()` so `fleetFreshness()`
  applies the identical rules; the public `freshness(snapshot, name, now)` signature and behaviour
  are unchanged.
- Justified new, view-local: `JOB_STATUS` labels/tones for the INV-FLEET-001 job state machine
  (queued/dispatching/accepted/rejected/failed/exhausted/unknown). `statusTone()` in `tones.ts`
  serves the operation/task vocabulary (for example it has no `dispatching`), `tones.ts` is outside
  the allowed paths, and the fleet states carry different meanings (`unknown` = ownership retained).
  Undefined status strings render raw with "(정의되지 않은 상태)" in the unknown tone.

## Contract typing (`snapshot.ts`)

- `Snapshot.sources` is now `Partial<Record<SourceName, Envelope>> & { fleet?: Envelope }`.
  `SOURCE_NAMES` is unchanged (`database, observations, docker, redis`), so:
  - the source strip still shows four sources plus the collector (its `xl:grid-cols-5` is intact);
  - header warnings, the retained last-good map in `use-snapshot.ts` and `buildReport`
    (`zeus-observatory-report.v3`, `sources`, caveats, denominators) iterate the same four names
    and never see fleet; old pinned reports are byte-for-byte the same shape.
- Added `FLEET_SCHEMA = "urn:zeus:fleet-status:1"`, `FleetLane`, `FleetJob`, `FleetUnregistered`,
  `FleetRegistered`, `FleetData` exactly as the SPEC wire contract lists them (projection fields
  only; no manifest, objective, repository path, schema name, DSN or raw error field exists in the
  type).

## View behaviour (`views/fleet.tsx`, nav label `팀 작업`, Lucide `Users`)

State matrix, evaluated in this order; each branch has distinct copy and none shows a zero:

| Input | Shown |
|---|---|
| no snapshot yet | destructive "응답 없음" · counts are 알 수 없음 |
| snapshot without `sources.fleet` | badge "출처 미제공" (unknown tone) + note that the collector predates the fleet source; other views unaffected |
| `status != "ok"` | destructive "fleet 출처 수집 실패" with envelope status/error and observed time; states that no last-good fleet record is retained |
| `status ok` but data off-contract (schema, `registered` not boolean, lanes/jobs not arrays, registered fields malformed, row shapes wrong) | destructive "fleet 데이터 해석 불가" with the reason; nothing rendered |
| observed time unparsable or >5s in the future | destructive "관측 시각 무효" notice above the data |
| observed age ≥ 20s | default "오래된 관측" notice with observed time and age; data still rendered as past |
| `registered:false` | "등록된 fleet 없음" as 비어 있음, explicitly "확인 불가 아님" |
| registered | board below |

Registered board, top to bottom:

1. Notices: `paused` → "admission 일시 정지" (new admissions blocked, dispatching work allowed to
   finish, resume is an owner host command, no control here). Ownership warning whenever any lane has
   `active_job` or any sampled job is `dispatching`/`unknown`: reservation, capacity and path
   exclusion retained, no automatic timeout/takeover/retry; when an `unknown` job exists the alert is
   destructive and says unknown is neither success nor failure and becomes `reconciliation_required`
   after restart without being cleared here. Lanes whose `active_job` is not in the sample are named
   as "(표본 밖)". `truncated` → "작업 목록이 잘렸습니다": the 100-job bound and that team/status
   counts are sample-only while `active_job` covers outside the sample.
2. Four stat tiles: admission (열림/일시 정지, with "열림 ≠ 서비스 실행 중"), active lanes /
   `max_parallel`, budget `per_host / total` labelled as call-count ceilings ("남은 금액 아님",
   enforced by CallBudget at start), 검토 수락 count from the sample labelled "병합·배포·완료 아님";
   when not fresh the accepted count is drawn in the unknown tone with "현재 아님".
3. Conceptual flow card badged "개념 경로 · 개별 작업의 실제 이동을 추적한 것이 아님": 소유자
   등록·투입 → admission (cap, one per lane, path exclusion, queued count, and the two dependency
   counts defined under "Dependency counts" below)
   → 레인 실행 (existing `zeus operate run`, isolated container, owner token, child stdout never
   proves acceptance) → 독립 검토 → 종단 상태 (accepted = exit 0 + matching lane operation +
   review accepted; no merge/deploy/retry) → 읽기 전용 투영 (this screen, observed time, PG read
   only). Vertical arrows below `lg`, horizontal at `lg`.
4. Team cards (`md:2`, `xl:3` columns): one per team found in lanes or jobs, description is the
   per-status count line for that team's sampled jobs (or 비어 있음), each lane with its
   `active_job` (lock badge, unknown tone when the sampled job is `unknown`, "(표본 밖)" when not
   sampled) or 비어 있음.
5. Job list (`md:2` columns, collector order, no re-sorting): status badge with hover note, id,
   team/lane, criterion, goal path, status meaning, operation id, reason code (없음 when null),
   dependencies with each prerequisite's label or "(표본 밖)", for queued jobs with dependencies a
   "의존성 판정" badge (see "Dependency counts"), calls reserved/settled (`null` → 확인 불가, never
   0), created, and "마지막 기록 · 마지막 실행 사실 · 생존 신호 아님". Queued jobs with dependencies
   get the rule text: how many prerequisites are outside the sample and therefore unreadable and not
   counted as unmet; whether a sampled non-accepted prerequisite confirms unmet; admitted only when
   all dependencies are 검토 수락; failed/rejected/unknown prerequisites block only this job;
   accepted is a candidate, the fixed base does not change.
6. Reading guide line repeating the 확인 불가 / 비어 있음 / 검토 수락 / 알 수 없음 / heartbeat / budget
   distinctions.

### Dependency counts (consolidated follow-up correction, 2026-09-18)

The rejected candidate f061306 computed one "의존성 미충족" count that treated a prerequisite absent
from the latest-100 sample as unmet. The projection cannot read the status of an out-of-sample job,
so absence is unknown, not a fact. `dependencyState(job, jobsById)` in `fleet.tsx` now classifies
each job from the sampled jobs only, evaluated in this order:

| Verdict | Condition | Counted as |
|---|---|---|
| `confirmed_unmet` (미충족 확인, error tone) | at least one prerequisite is in the sample and its status is not `accepted`; this wins even when another prerequisite is absent | "의존성 미충족 확인 N건" |
| `unknown` (표본 밖 · 알 수 없음, unknown tone) | no sampled non-accepted prerequisite, but at least one prerequisite is not in the sample | "표본 밖 의존성(알 수 없음) N건", never added to the unmet count |
| `all_accepted` (모두 검토 수락 (표본), success tone) | every prerequisite is in the sample and `accepted` | neither count; the badge says admission is still a separate decision |
| `none` | no dependencies | neither count |

The admission flow node shows both counts on their own line plus the meaning line "확인 = 표본 안
선행 작업이 검토 수락 아님 · 표본 밖은 미충족으로 세지 않음". Only queued jobs are classified for the
counts. Job-level disclosure stays: each prerequisite is listed with its sampled label or "(표본 밖)",
the "의존성 판정" badge shows the verdict with its hover note, and the rule text states the number of
out-of-sample prerequisites and that they are not counted as unmet. The truncated notice adds the
same sentence. Nothing else in the accepted view changed; `truncated:false` with an absent
prerequisite still yields `unknown`, because the collector's sample is the only evidence this screen
has either way.

Owner reproduced the pre-fix false count with a browser-only synthetic envelope (SPEC, consolidated
follow-up). This worker did not run a browser or the TypeScript checker; the synthetic shapes that
exercise the three verdicts are: queued job depending on a sampled `failed` job (confirmed unmet);
queued job depending only on an id absent from `jobs` (unknown); queued job depending on one sampled
`failed` and one absent id (confirmed unmet, with the out-of-sample sentence still shown).

No HTTP mutation control, no fetch, no timer and no state of its own: the view is a pure render of
`snapshot` and `now` from the existing `useSnapshot`. Because `use-snapshot.ts` is outside the
allowed paths, fleet is not in the retained last-good map; the "collector failure" branch says so
instead of showing an older board. The previous snapshot object itself is still what `useSnapshot`
keeps when a request fails, so a transport failure shows the last fleet board with the header's
transport warning and, after 20s, the stale notice.

Mobile/dark: every grid collapses to one column below `md`/`lg`; badges and ids use
`break-words`/`break-all`; only existing tokens (`success/warning/error/unknown`, `card`, `muted`)
are used, so the dark theme applies without new CSS. Not verified in a browser here.

## Verification

Run here (restricted worker, no npm, no node_modules present):

- `python -m pytest tests/test_monitoring.py -q -p no:cacheprovider` — result in the worker answer
  (original UI operation only).
- `python -m ruff check .` — result in the worker answer.

Consolidated follow-up correction (fleet-001-fix-ui): only `python -m ruff check .` was run, as
assigned; the pinned base keeps the two known monitoring assertion failures that the backend lane
owns, so pytest was not run by this worker. Git reads were denied in the worker sandbox, so the base
revision was not confirmed by the worker.

Neither command exercises the TypeScript files. Not run by this worker and owed to the owner:
`npm run typecheck`, `npm run lint`, `npm run build`, browser acceptance at 390px and in dark mode,
and the real PG projection through the collector and unprivileged HTTP reader. Lucide icon names
used (`Users, Workflow, GitBranch, ShieldCheck, Layers, ListChecks, Lock, Pause, CircleHelp,
AlertTriangle, ArrowDown, ArrowRight`) could not be checked against the installed package; the
owner's build resolves them. Synthetic fixtures for the unknown/empty/truncated rows of the
acceptance matrix were not added (no frontend test harness exists in this checkout); the branches
are reachable purely from the envelope contents, so the owner can exercise them by serving a
snapshot with `sources.fleet` set to each shape. These are explicitly not production executions.
