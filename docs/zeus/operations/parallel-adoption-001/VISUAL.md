# Lane B — picture-first report (Sterk #82 adaptation)

Worker note for parallel-adoption-001, base 14956d22485c709504e575a52a65a914d81f2aa8, 2026-09-18.
Scope: `frontend/monitor/src/views/report.tsx`, `components/report-explainer.tsx`, new
`components/report-visual-summary.tsx`, `index.css`, this note. No backend, HTTP, schema, test,
dependency, packaged asset or Lane A file was touched.

## Disposition: migrate presentation, reuse the pinned object

- Authority for every figure stays `buildReport` in `src/lib/report.ts` (schema
  `zeus-observatory-report.v3`, unchanged). The view adds no count: the new component reads
  `report.counts`, `report.sources`, `report.completeness`, `report.transport`,
  `report.critical_events(_total)` and `report.explanation.{operations,caveats}` and shows
  percentages only next to both numerator and denominator.
- The operation status bar chart and the caveat list previously drawn inside `ReportExplainer`
  migrated to `ReportVisualSummary` so they sit on the first screen; the explainer no longer
  renders them (one renderer per figure, no duplicate chart). Explainer keeps summary, conceptual
  flow, reading guide and provenance and now sits behind a disclosure.
- Existing modules reused: `StatCard`, `StatusBadge`, shadcn `Card`, tones (`severityTone`,
  `freshnessTone`), labels/orders from `src/lib/snapshot.ts`, Lucide icons already pinned in
  `package-lock.json`. No new dependency.

## First screen (top to bottom)

1. Existing header, pinned line ("고정 보고서 · 생성 …", age) and the destructive alerts for
   transport failure, missing snapshot and unusable observations source — unchanged, never collapsed.
2. Four stat tiles: 이벤트 (샘플), 치명·오류, 운영 결과, 경보 기록. `null` renders "확인 불가"
   in the unknown token colour with the note "0 아님"; zero renders "0" with "비어 있음".
3. Source-state diagram (CSS grid, Lucide icons): four source nodes (freshness label + envelope
   status + observed time + error text + sample limit/truncation on the observations node), arrow,
   snapshot node (collected time, scope label, "스냅샷 없음" when no response), arrow, report node
   (generated time, transport state at capture, last ok response, informational_only). The path is
   badged "개념 경로 · 개별 기록의 실제 이동을 추적한 것이 아님"; node states are the captured values.
4. Three bar charts: 분류별 이벤트, 심각도별 이벤트 (denominator `counts.events_total`),
   관측된 운영 결과 분포 (denominator `explanation.operations.denominator`). Each row prints
   `label · N건 / D건 (P%)` as text; the bar is `aria-hidden`. Known keys appear in the existing
   order including zeros; undefined stored keys are appended raw and labelled "(정의되지 않은 값)".
   A footnote states when the per-key sum differs from the total instead of hiding it.
5. "이 캡처의 한계" card: `explanation.caveats` (transport, non-fresh sources, truncation,
   uninterpretable values, local spool, no receipts) always visible.

Chart states are distinct: `unknown` (dashed unknown-tone box, "분모가 없음 · 0건이 아니라 알 수
없음"), `empty` (dashed box "0건 · 비어 있음 · 알 수 없음 아님"), `observed` (bars).

## Disclosures and print

Long records use native `<details>/<summary>` (`Disclosure` in `report.tsx`, class
`report-details`): 쉬운 설명, 범위·시각·완전성 한계, 건수 표, 운영 결과 목록, 치명·오류 이벤트 목록,
다음 조치와 근거 ID. Each summary line carries the section's state or count so a collapsed section
still reports "확인 불가" versus "비어 있음" versus `N건`. Closed by default on screen.

Print: a `beforeprint` listener opens every closed `report-details` inside the view and
`afterprint` restores them; `index.css` adds `.report-details::details-content
{ content-visibility: visible }` under `@media print` as the engine-level backstop and
`print-color-adjust: exact` on chart tracks. JSON download and pinning logic are untouched:
`useState(() => buildReport(...))` and the regenerate button are as before, and the printed page
still describes the same pinned object.

## Mobile, dark mode, accessibility

Tiles use `grid-cols-2` below `lg`, sources `grid-cols-2` below `sm`, charts single column below
`lg`; all nodes carry `min-w-0 break-words`, matching the existing 390px conventions. Colours
come only from the existing semantic tokens (success/warning/error/unknown/primary), so dark mode
inherits. Lists are labelled via `aria-labelledby` on card titles; icons are `aria-hidden`; the
conceptual-path badge and every state label are text.

## Not claimed / owner checks

- Not run by the worker (per objective): `npm run build`, `npm run lint`, `tsc`, browser checks
  at 1440px and 390px, dark mode, print/PDF, regenerate/pin/JSON equality, synthetic unknown/
  empty/truncated inputs. Node is present in this container but `node_modules` is absent, so
  even a typecheck was not possible here; the TypeScript is unverified by compilation.
- No goal completion, cost or team timeline figure is shown; none exists in the report object.
- Lucide names used: AlertTriangle, ArrowDown, ArrowRight, Camera, ChevronDown, Container,
  Database, FileText, RadioTower, ScrollText. Availability in the pinned `lucide-react` version is
  an owner build check.
- Follow-up note (not done): `docs/zeus/operations/observatory-001/IMPLEMENTATION.md` describes
  the explainer as owner of the operation chart; it is outside Lane B's allowed paths.
