# Parallel adoption 001 — context discipline and visual reports

Codex owns analysis/design/acceptance; actual Zeus Claude workers implement. 2026-09-18.
Base 510bc22d009ceecd2aa969eda0c2bfeb8d73a813. This is ONE bounded delivery, not whole-harness completion.

## Outcome and authority

User authorizes comprehensive local Claude experience adoption, Sterk-reference adaptation,
parallel bounded operations and picture-first reports. Deliver two independent changes through
two concurrent isolated Zeus operations, review and integrate them, and verify/deploy the report.
Existing public runtime, dirty analysis files, credentials and machine call ledger stay intact.
No automatic merge/retry, no reference source copy, no arbitrary background task generation.
Finish: both changes independently reviewed, integrated checks/CI/browser pass, actual parallel
execution and limitations recorded, report deployed. Failed worker outcomes remain failures.

## Evidence, architecture and decisions

Existing docs/design.md:169 defines context as compiled, versioned SSOT input with required,
selected and external-reference layers. Keep this canon; do not create a competing context system.
Git owns definitions, PG runtime observations, D large evidence. The dirty full-analysis ledger is
not replaced or committed by this task. Entire local asset/experience analysis remains the long-term
denominator; inventory, semantic review, implementation and operational evidence are distinct states.

Experience source: docs/full-analysis/harness-experience/{README,trace}.md, pinned upstream
a3f8b3be9a0a389329de6e16a6c7db81782041a3, partition 93 paths +25 observed versions. T1/T2 show
repeated ingestion counted as recurrence, unrelated PASS attached to lessons, corrected bodies
not superseding old lessons, lifetime FAIL confused with current incident. These are source-review
findings, NOT current Zeus runtime defects or fresh executions. Absorb the resulting worker
evidence discipline, not the source implementation or its authority claims.

Sterk #82 describes report rendering, scope/time disclosure and unknown values; #89 work board
is a later migration candidate. Existing Sterk analysis is historical UI observation, not source
access. Preserve Zeus PG SSOT; do not adopt the issue's file-SSOT suggestion. #75/#76/#99/#100
already partially informed monitor work; do not restart that accepted work.

Current LocalCycle._candidate refuses foreign active same-role work and _deliver refuses active
foreign correlation. Therefore this pilot uses two explicit PG schemas (no public fallback), Redis
namespaces and runtime artifact roots, plus detached source checkouts and isolated worker containers.
Both lanes use the SAME default machine CallBudget ledger and fixed total ceiling. This is logical
operating isolation, NOT a database privilege/security boundary. Existing shared-queue safety stays.
Lane records remain in their PG schema and evidence report; public monitor does not aggregate those
schemas. A permanent multi-lane dispatcher/federated monitor is a subsequent explicit delivery,
not claimed by running these two operations. The new report layout applies to current public data.

Path: pinned goal/spec -> two manifests -> per-lane PG/outbox -> Redis Streams -> isolated Claude
-> evidence inspection -> independent Codex review -> terminal receipt -> owner integration/CI ->
public read-only report deployment. Uncertain execution blocks only its lane and remains owned.
Fixed initial budget: four calls total (two Claude, two reviewers); USD4 declared Claude CLI ceiling
per lane, 900s worker timeout. No failure retries without a material acceptance reframe.

Primary sources read 2026-09-18:
- PostgreSQL 18 docs /ddl-schemas.html: search_path names logical table namespace; schemas do not
  imply privilege isolation. Use one explicit schema, no public fallback.
- https://ui.shadcn.com/docs/theming: existing semantic CSS tokens are the style authority.
- https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details: native disclosure
  supports optional detail; vital uncertainty must remain outside collapsed sections.
Frontend versions remain package-lock.json pinned (React19, Vite8, shadcn source components).

## Lane A — experience-aware worker context

Modify ONLY worker-profile-v1.md, its metadata JSON, and EXPERIENCE.md beside this file.
Integrate concise guidance into existing headings; remain <=6000 normalized characters. Do not
add a separate always-loaded skill or duplicate existing SSOT/investigation rules.
When consuming experience: bind source revision/content, incident/run and applicability; repeated
reading is not independent recurrence; unrelated PASS is not validation; preserve corrected or
superseded source and distinguish resolved history from current incident. Keep full evidence by
reference, inject only task-relevant lessons; unavailable/contradictory evidence stays unknown.
Record two source-to-rule mappings and remaining behavioral-efficacy limits in EXPERIENCE.md.
Guidance is not mechanical enforcement, proof of model obedience or formal knowledge promotion.
Worker commands ONLY metadata helper per AGENTS, focused worker profile tests, and ruff.

## Lane B — picture-first report, Sterk #82 adaptation

Modify ONLY frontend/monitor/src/views/report.tsx, components/report-explainer.tsx,
components/report-visual-summary.tsx (optional new component), index.css, and VISUAL.md here.
No new dependencies, backend, report schema or counts; use the existing pinned Report v3 object.
First screen: concise headline, source-state diagram, category/severity visualization and actual
operation outcome chart. Prefer semantic SVG/CSS using existing tokens/Lucide, visible labels
and numeric denominators. A conceptual path MUST be labelled conceptual, never actual stage trace.
Move long detailed records into accessible native disclosures; print must include evidence and
limitations. Keep source failure/staleness, truncation, unknown and capture time visible even when
details collapsed. Unknown is not zero; empty has an explicit state. No invented goal completion,
cost or team timeline because those aren't present in this snapshot. Mobile390px no body overflow.
Preserve pinned regeneration/JSON/print, dark mode and existing external-reference semantics.
Worker runs ONLY focused existing monitoring Python tests and ruff; owner runs npm/build/browser.

## Acceptance matrix and one integration batch

| Path | Deciding evidence |
|---|---|
| Actual normal/concurrency | two real operation time intervals overlap; lane task/correlation sets disjoint |
| Budget/ownership | shared ledger delta <=4, no unreadable slot, no resets; same containers/profile controls |
| Failure/unknown/cancel | terminal failure remains failure; no implicit retry; unknown effects retain evidence; no public queue mutation |
| Restart | existing operation same-ID replay rules retained; no automatic takeover claimed |
| Context | metadata digest/size and packaged-profile tests; source-to-rule review; efficacy not inferred |
| UI normal | build/lint, real public snapshot, diagram labels/data match report JSON |
| UI unknown/empty/truncated | browser synthetic inputs explicitly labelled, visible unknown and scope |
| UI capture/print/mobile | pinned data survives refresh, 390px layout, PDF readable with evidence details |
| Platform | Windows local checks; existing Windows/Linux CI; no WSL model execution claim |
| Cleanup | own workers finish; preserve lane schemas/artifacts for audit; no blanket deletion |

Owner commits this frame, runs lanes, reviews against this matrix, integrates disjoint diffs,
builds static assets, performs browser/full CI, merges/deploys within existing authorization.
Recommendations outside this matrix remain notes. Full asset absorption is tracked in the existing
analysis ledger, not reported as two-item completion or a percentage derived from file counts.

## One pre-provider preparation correction

Both initial lane attempts failed during stage_source materialization with FileNotFoundError on
deep tracked evidence paths, before the adapter's container create call. Each reserved a machine
slot (146 ->148); neither produced candidate code or a worker run record. Preserve both failed
operations and unsettled_unknown reservation records; do not rewrite them as successful calls.
Discriminating check: exact same source revision, existing stage_source and 5062 files/59,597,999
bytes exported successfully under a shorter D runtime prefix (path-probe.json). No source fix,
model call, public runtime cleanup or OS setting change was used. Thus shorten only the two
owned runtime roots to D:/workspaces/zeus/artifacts/p1e and p1v. Original partial copies remain.
Owner authorizes one corrected pair of distinct operation IDs after this measured setup correction;
same lane schemas/namespaces, fixed global ceiling152 (148 existing +four intended calls), not a
reset/retry of the old IDs or an automatic escalation. Original unknown reservation status remains
visible; code order and absent run/container establish source preparation failed before creation.

## Continuing whole-experience programme (not added to this delivery's gates)

The user requires maximum comprehensive absorption. The existing path-ledger/coverage remains the
analysis authority; existing operational specs/implementation records remain adoption evidence.
The local snapshot presently enumerates 2736 tracked paths and 707 unreviewed paths, with an
additional separately inventoried local-assets population. These are coverage counts, not an
adoption percentage or a claim all reviewed paths are semantically complete. Dirty ledger bytes
were preserved under the raw reference-index; do not silently publish them as accepted main.

Each future batch links source revision/content -> experience/contract -> current Zeus owner ->
reuse/improve/migrate decision -> verification -> integrated release. Repeated sources map to one
contract; rejected methods remain negative lessons with applicability and evidence. Corrected
experience supersedes old conclusions without deleting their provenance. Credentials/private
session material stays outside ingestion. No relevant technical experience is discarded without
a recorded disposition. Full text and logs stay referenced, not always injected into every prompt.

| Dependency group | Existing authority / Sterk reference | Next admission condition |
|---|---|---|
| Context and experience | docs/design.md; full-analysis; #87 skills, #88 memory | existing context/profile mechanism first; no second knowledge store |
| Goal and backlog scheduling | goal_progress, operations; #79 requests, #81 backlog, #97 goals | goal/criterion binding and fixed batch ceiling, no recursive task spawning |
| Multi-lane runtime | current Operation/LocalCycle; #89 board, #90 roles, #91 workers, #92 fleet | owned lane mapping, conflict/dependency admission and aggregate read-only visibility |
| Reports and explanations | pinned Report v3; #82 reports, #84 wiki, #93 usage | actual metrics only; unknown costs and historical data labelled |
| Human decisions | existing decision authority; #78 inbox, #96 asks | scoped question, durable answer, no fabricated approval |

Other reference pages remain in the 27-issue catalogue (#74 index), not silently adopted or closed.
Read their actual contracts/evidence when their goal is admitted. This map is a dependency queue,
not five mandatory pre-operation projects. Independent write scopes can execute together; common
contract migrations and merge/deploy steps stay ordered. The next reusable control-plane delivery
must make lane definitions, global admission/budget and cross-lane reporting first-class, rather
than accumulating task-specific shell launchers. This pilot's scripts are evidence orchestration.

Progress reports distinguish source coverage, accepted migrations, actual completed operations,
unknowns and reopenings; ticket count, token use and repeated test runs are not progress by themselves.
