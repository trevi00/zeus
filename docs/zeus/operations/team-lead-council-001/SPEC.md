# Topic-bound team-lead council — one delivery frame

Date: 2026-09-17. Owner/base: Codex / 192b8da04471ea1ef81574ff7b2fe2831cd733b3.
User authorized building research-lead proposal + DBA current-state report ->
improvement-lead alternative -> conductor arbitration. Claude implements; Codex
designs, independently verifies and decides Git acceptance. Existing dirty analysis
documents are outside this task. New artifacts/worktrees remain on D.

## Outcome and bounded scope

Add an opt-in autonomous v2 council mode, not a cosmetic rename. Preserve v1 exact
semantics, direct operation maintenance entry points, critical-only blocker policy,
one round/deadline, six-W/Redis delivery, execution provenance and post-review PG
promotion. No automatic merge/deploy, new web search engine, arbitrary SQL/model DB
credentials, full graph-search platform or endless debate. Operator/owner research
can supply primary references through pinned Git material as today. No claim of a
live new council until actual provider executions are measured.

Completion: implemented v2 path + meaningful existing/new contract tests + real
isolated PG snapshot tests + independent owner review + full CI and PR merge.
Fixtures prove contracts, not model debate quality. One actual Zeus maintenance
operation (Claude then Codex review), maximum2 starts; ledger64 -> ceiling66.
Claude declared budgetUSD12, timeout1800s. Stop/reframe on failure, no automatic retry.
Do not run the new seven-call council as part of this implementation budget.

## Facts, decisions and unknowns

- Existing domain/autonomous.py v1 fixes researcher/proposer/attacker/arbiter and6
  starts. application/autonomous.py freezes Git-backed research then loops debate
  roles, invokes Operation v2 and promotes after worker/reviewer artifact checks.
- adapters/autonomous_roles.py uses strict model output shapes and clean pinned
  checkouts; role binding currently derives agent IDs from the old role names.
- resources/organization.json already has research/improvement leads, but no DBA.
  domain/model.py requires direct parent task assignments; conductor self-arbitration
  needs a narrow explicit exception, not a broad hierarchy bypass.
- Store.transaction currently serializes writers; it is not a read-only snapshot
  contract. New DB observation must use a separate read-only adapter, not scan all
  operational rows or expose model-generated SQL.
- PostgreSQL18 documentation, opened2026-09-17:
  https://www.postgresql.org/docs/18/transaction-iso.html#XACT-REPEATABLE-READ
  Repeatable Read gives one stable transaction snapshot; Read Committed can see
  different snapshots per statement. This supports a REPEATABLE READ READ ONLY
  observation transaction, not a cross-Git/PG atomicity or freshness guarantee.
- Redis Streams transport is already shipped; no transport behavior change is
  necessary. External Redis doc fetch failed; no new claim relies on it.
- Unknown: topic-wide record discovery/completeness and model semantic accuracy.
  Explicit bounded record selection below names coverage; no row != no capability.

## Complete path and contract

1. New `urn:zeus:autonomous:2` has the existing v1 fields plus `current_state`:
   `{records:[{bucket,id}], max_age_seconds}`. 1..20 unique explicit records; buckets
   tasks/operations/autonomous_runs/promotions only; safe token IDs; max_age integer
   60..3600, no bool. v1 fields/canonical form unchanged. New max starts7.
2. Research executes at base and freezes the existing packet (Git SSOT, sources,
   facts/inferences/unknowns). New mode reuses this evidence path, not fake outputs.
3. A host read-only snapshot port collects the selected PG records in ONE read-only
   repeatable-read transaction, with bounded connection/statement timeouts. Snapshot
   envelope binds topic/run/base, selection, observed_at, expiry and database identity
   digest (no DSN). For each requested key: found/missing, SHA256 of canonical full row
   when found, and a SMALL whitelist of validated status/stage fields. No row bodies,
   free text, errors, prompts, credentials, arbitrary paths or unbounded scans. A
   malformed row/status is unknown, not guessed successful. Connection/read failure
   refuses this run; do not turn failure into an empty observation. Missing key means
   only absent at that snapshot in the explicit scope. Schema identity participates
   in endpoint digest so another schema is not silently the same observation.
4. Persist the snapshot content-addressed in executor artifact storage. Store only
   references/digests and safe metadata in the run receipt. DBA (`lead:dba`) gets
   this snapshot + exact research packet/SSOT, returns a report naming snapshot_digest,
   concise summary, relevant claim_ids, unknowns. Verify digest/known claims and bind
   task/session/artifact/reservation as for every other role. Report is interpretation,
   never a substitute for original observation or a new Git-supported fact.
5. Research lead (`lead:research`) proposes using the packet AND frozen DBA report.
   Improvement lead (`lead:improvement`) responds with constructive alternative:
   summary, decision reuse/improve/migrate/new, rationale, transition (compatibility,
   rollback, retirement for improve/migrate), claim_ids, plus existing critical/minor
   findings. Both see identical snapshot/report identities. Critical findings still
   need reachable trigger, criterion, impact, mitigation. No compulsory objection.
6. Conductor (`conductor`, real agent identity, not lead:arbiter relabelled) receives
   both contributions and arbitrates using existing verdict/dispositions rules. The
   existing DGE event roles proposer/attacker/arbiter may remain INTERNAL compatibility
   slots, but the full improvement proposal must be retained in role output/evidence
   and delivered to conductor; do not discard it when deriving findings-only event.
   Receipt/CLI/runbook exposes actual agent and responsibility mapping.
7. Use actual six-W outbox -> Redis -> tasks/executor for DBA and conductor too.
   Add only the necessary conductor-to-self dge_role arbitration task/result authority;
   prohibit general self-assign and worker impersonation. Workflow must still verify
   persisted task results. Route DBA reporting through the conductor relay according
   to the existing organization tree; report is delivered to the improvement lead,
   without silently allowing arbitrary peer assignments.
8. Before each downstream debate role/implementation, check snapshot freshness using
   the SAME frozen observed_at/expiry. Missing/corrupt/mismatched/stale evidence stops
   with an explicit reason, no refresh mid-debate. No model verdict repairs a snapshot.
9. Approved design invokes existing Operation v2; promotion only after independent
   implementation/review evidence. Include DBA binding + snapshot/report digests in
   final provenance and reverify new role artifact binding at promotion. Independent
   sessions remain mandatory. No promotion on missing report/failed role/late result.
   Terminal re-entry is cached, interrupted residue refused; no automatic takeover.

Prefer a small council domain helper and read-only snapshot adapter; reuse existing
autonomous state machine and artifact/observation ports. Thread version-aware role
mapping/caps explicitly through domain, executor role adapter, app and CLI. No global
mutation of legacy constants to impersonate v2. Snapshot adapter accepts injected
ports in unit tests and uses real PG in integration tests; model mocks are explicitly
fixtures, never reported as actual council execution.

## Fixed acceptance matrix

| Boundary | Required evidence |
|---|---|
| Normal | v2 research -> snapshot -> DBA -> research lead -> improvement lead -> conductor -> existing implementation/review -> promotion; correct real agent IDs and shared report |
| Compatibility | existing v1/DGE/operation tests unchanged in semantics, cap6 retained; v2 cap7 |
| Input | unsafe/duplicate/oversized selections, wrong buckets/types, unsupported version refused pre-provider |
| Unknown/failure | selected missing record explicit; DB unavailable/malformed/corrupt evidence not empty/success; zero subsequent model starts |
| Time | snapshot age and absolute deadline checked at role/implementation boundaries; no implicit refresh/extra round |
| Ownership | exact topic/base/run, snapshot digest, task/attempt/reservation/output; swapped DBA report/session/agent refused |
| Hierarchy | real conductor arbitration self-loop only; ordinary conductor/worker self-assign still refused; report passed to improvement through relay |
| State | same-id terminal cache has no calls; running residue/concurrent owner refusal; no topology change for same run |
| Promotion | missing/tampered DBA or snapshot cannot promote; model design agreement alone cannot promote; no weakening prior accepted worker/reviewer checks |
| Privacy/logs | general transport + dev role stages + operational failure reasons via existing observer; credentials/canary row text absent from report/CLI/logs; no raw exception chains |
| Real PG | isolated schema, real records including missing; fixed transaction snapshot, read-only failure on writes; source records unchanged; selection bounds |
| Platform/cleanup | portable paths and existing CI Windows/Linux; no new subprocess/process lifecycle; fixture schemas/files owned and cleaned; raw on D |

Batch: Claude implements/tests/runbook/contracts once; Codex reviews full matrix and
runs adjacent contracts + real PG lane, CI owns full suite. Noncritical discoveries
are recorded once with impact/trigger; do not extend the current goal.

## Metrics and handoff

Record topology, exact role/task/session identities, selected coverage, snapshot age,
unknown/refusal counts, starts/cap and outcome. These measure this run, not absolute
feature completeness or the truth of model prose. New UI dashboards, autonomous
topic selection and cost optimization are outside this delivery.

## Reframe: unfinished first implementation, bounded completion

Run-001 stopped with `claude-provider-timeout` after one actual start (ledger64->65).
No independent reviewer ran. Twelve unfinished files were preserved byte-for-byte at
271e1ab; raw manifest/receipt and source hashes remain under the task artifact root.
This is unfinished implementation, not an accepted or rejected completed candidate.

Owner preflight at271e1ab:53 passed/6 failed across council/autonomous roles; real PG
test failed (valid worker:implementation classified unknown); ruff E731 in new fixture.
The first PG attempt lacked a DSN and is recorded as owner invocation error; the
subsequent isolated PG run reached the adapter and reproduced the classification bug.
The normal fixture cycle stops at evidence_reservation_unbound: new role stages must
be represented accurately by the fixture, not weaken the production evidence check.
The improvement output is transformed by attacker_findings twice, losing required
critical trigger/impact/mitigation before event_from_role. Keep one authoritative
conversion. Synthetic owner probes also confirmed an arbitrary token-shaped status
was copied verbatim and a supplied connection error was exposed by traceback chains.
These probes are injected faults, not observed production credential exposure.

One continuation from the preserved implementation (no restart from scratch): finish
the above normal/privacy boundaries, existing/new tests, RUNBOOK and contract entry.
Use finite domain status/stage allowlists and known actor/namespace syntax instead
of exporting arbitrary token-shaped row fields. Missing required status is unknown;
normal colon-bearing actor identities must remain readable. Public snapshot failure
tracebacks must not retain raw adapter exceptions. Keep report/source unknown semantics.
Add focused regression coverage for these observed failures and verify unknown claim
IDs cannot enter the improvement alternative unnoticed. Preserve existing v1 semantics.

Actual DB is PostgreSQL17.11; owner also opened17 transaction-iso and sql-set-transaction
on2026-09-17 and confirmed the same snapshot/read-only semantics. Record this version
in the runbook; the earlier18 reference was not a local version observation.

Continue through existing operate with a new run ID/schema at the preserved candidate,
maximum2 starts (Claude completion + Codex review), ledger65->ceiling67. Claude budget
USD12, timeout3600s; no new seven-call council execution. This is owner-directed bounded
completion of the same frame, not automatic retry, failed-output repair or promotion.
After the fixed checks pass, deliver normally; do not expand into unrelated research.

## Owner disposition of the completed candidate

Candidate426e413: owner contract lane198 passed/1 skipped, isolated real PG1 passed,
ruff passed. Independent Zeus Codex review ran65 focused checks successfully but
returned accepted=false for one P2: missing operations.lead_accepted is conflated
with explicit null by body.get(), so that synthetic row is reported found instead
of unknown. Owner independently reproduced it; it is not fixed or waived silently.

Under the user's critical-only blocking rule, this is an accepted noncritical
residual for this delivery: the actual status is still reported, null grants no
approval, and the original worker/reviewer/promotion gates remain separate. The
required-field completeness criterion has this explicit exception. Fix key-presence
checking on the next bounded snapshot-maintenance task; revisit sooner if incomplete
operation rows occur in a selected real topic or anyone starts using snapshot
coverage as an approval decision. No current caller has that authority.

The run stays rejected in PG; the reviewer output is preserved unchanged. Owner Git
acceptance, contingent on full CI, is separate and does not create an accepted
operation or knowledge promotion. No third implementation/model round for this P2.

## Live council validation, 2026-09-17

The user authorized the next actual operation. Goal: exercise the shipped seven-role
path on one small maintenance topic: distinguish an absent required snapshot field
from explicit nullable lead_accepted. This is a new council canary after framework
delivery, not a retry of the rejected construction operation. Keep that verdict intact.

Inputs are pinned Git definitions and the actual operation/task records from
zeus_team_lead_council_002. Reuse that isolated schema to observe real history; give
this run its own id, Redis namespace and runtime directory. These records establish
prior execution states, not occurrence of a malformed row in production. The known
missing-field reproducer is synthetic. Source semantics and PG17 references above
remain applicable; no new platform or database behavior is introduced.

Path: research -> frozen packet -> read-only snapshot -> DBA interpretation ->
research lead proposal -> improvement lead alternative -> conductor arbitration ->
Claude implementation -> independent Codex review -> verified graph promotion.
Codex owns this frame and final acceptance; Claude alone makes runtime changes.
Maximum seven starts, machine ledger 67 to 74, one round, 60-minute absolute
deadline; Claude USD4 declared ceiling / 1200 seconds. No automatic retry or merge.

Acceptance matrix for this phase:
- Normal: all five design roles bind to distinct executions and shared evidence;
  Claude implements the small fix, independent review accepts, promotion is bound.
- Missing/unknown: absent lead_accepted becomes unknown with no exported fields;
  explicit null/false/true remains found. Existing missing-row behavior is unchanged.
- Failure/timeout: retain original terminal receipt and raw evidence; no repair of
  model answers and no promotion on refusal. Do not rerun until green.
- Restart: cached terminal replay uses zero additional calls and no extra promotion.
- Concurrency/platform: existing council checks and CI cover unchanged boundaries;
  this live run is Windows only, not evidence of a WSL live council.
- Cleanup: collect observation spool, inspect unsettled reservations/unconfirmed
  executions, preserve runtime and artifacts on D; do not erase historical runs.

One batch: tiny domain fix + regression + runbook nullable clarification; targeted
council tests and lint, independent review, owner provenance check, full CI for any
resulting PR. Broader topology, automatic recovery, device/product acceptance and
remaining reference absorption stay out of scope. A refusal is a measured limitation,
not a reason to expand this task into exploratory environment repair.

Live phase result: accepted/promoted first execution, seven calls/settlements;
cached replay zero calls, one graph promotion, historical rejection unchanged.
Owner66 tests (including real PG) and lint passed. See LIVE-001.md and its evidence
manifest. The missing-key exception above is now resolved by the candidate; broad
continuous operation and product acceptance remain outside this delivery.
