# research-program-001 — implementation notes

Worker delivery for `SPEC.md` (contract INV-RESEARCH-PROGRAM-001). Framework construction only:
no model call, no real feed fetch, no PostgreSQL, no service and no Git command against the user's
checkout was made by the worker. The owner canary and CI are separate unexecuted steps.

## Files

| Layer | File | Role |
|---|---|---|
| domain | `src/codex_harness/domain/research_program.py` | strict config (`urn:zeus:research-program:1`), URL/local identity, keyword relevance, stable order, headroom/selection rule, capture path/ref, derived council manifest, result folding from the run row, schedule rules, status/monitor projections |
| application | `src/codex_harness/application/research_program.py` | `ResearchProgram`: register (immutable, cached, conflict), pause/resume, one-transaction cycle reservation, dedup+claim+adoption reservation in one transaction, capture/council-start/council-result/fail/complete records, read-only status, monitor |
| adapter | `src/codex_harness/adapters/research_program.py` | `collect_live` (both feeds via existing `ResearchSources`), `collect_local` (dge `verify_sources` at base), `GitCapture` (temporary index, detached commit, one new ref), `EventLog` (JSONL, three categories), `render_report`/`write_report`, `ProgramRunner.tick/run` |
| adapter | `src/codex_harness/adapters/research_program_cli.py` | `zeus research-program register|run|status|pause|resume`; run wires `ResearchSources`, `GitSource`, `GitCapture`, `CallBudget`, `FileArtifacts`, `autonomous_cli.run` |
| wiring | `src/codex_harness/cli.py` | parser registration and `research_program_command` (exit 0 only for a recorded/replayed/read result) |
| monitor | `src/codex_harness/adapters/monitoring.py` | additive `research_programs` source in `collect` (`research_program_facts`), fails independently |
| tests | `tests/test_research_program.py`, `tests/test_research_program_cli.py`, `tests/test_research_program_fixtures.py` | matrix below; `test_monitoring.py`/`test_monitoring_observations.py` source-set assertions updated for the additive envelope |
| docs | `docs/contracts.md` (INV-RESEARCH-PROGRAM-001), this file, `RUNBOOK.md`, `example.json` | |

## Full path (one tick)

0. Review001 corrections (see `CORRECTION.md`): the runner passes the current repository identity
   to `reserve_cycle`, which raises `repository_mismatch` before anything else; the post-capture
   pre-provider stages are tracked and a failure is a blocked receipt with the capture retained
   (or `recorded: false` with ownership kept when the store cannot record it); the capture blob is
   written from exact bytes, hash-checked and read back before the ref exists.
1. `reserve_cycle`: one store transaction. Refuses `repository_mismatch`, `busy` (owned cycle), `paused`,
   `program_completed`/`program_blocked`; completes on `deadline_expired`/`max_cycles_reached`;
   `not_due` returns without increment. Otherwise writes the cycle row (`collecting`, owner token)
   and advances `next_cycle`. PostgreSQL serializes this through the existing store advisory lock.
2. Discovery, no transaction open, no model: `collect_local` re-verifies every owner-authorized
   row at `config.base` (dge codes on failure → local `unavailable`), `collect_live` fetches
   GitHub Trending and GeekNews through `ResearchSources.collect` (raw body into `FileArtifacts`,
   bounded title/summary, https URL normalized without fragment; failure → `unavailable` with the
   exception type only). `CallBudget.counts()` is read (unreadable → no headroom).
3. `record_collection`: one transaction. Dedup by `local:<path>` / `url:<normalized>`; new
   candidates get a deterministic keyword reason (`keyword:<kw> in title|summary` or
   `no_keyword_match`); local rows are `owner_authorized_local_candidate`. Selection: first eligible
   unclaimed in stable order, only if `adoptions < max_adoptions` and headroom ≥ 7 on both
   ceilings; the claim and `adoptions += 1` are in this transaction. Counts, source map, budget
   snapshot and selection reason are persisted on the cycle.
4. No selection → `complete_cycle` (counted). Selection → snapshot JSON (candidate identity/reason,
   source-status map, local bytes digest at base, optional `github_detail` result or
   `{"status": "unknown", "code": <type>}`), artifact put, `GitCapture.capture` (refuses existing
   path/ref, base missing, oversize), `record_capture`.
5. `derive_manifest` → canonical `urn:zeus:autonomous:2` manifest (validated by the real validator
   in tests) written under `runtime/research-program/<id>/manifests/` and to the artifact store;
   `record_council_start` persists run id, digest and reference BEFORE the council.
6. `autonomous_cli.run(service, args)` (existing CouncilRun, budget, promotion). Its return value
   and any exception are ignored as authority; the `autonomous_runs` row is read and folded by
   `council_result` (id + manifest digest must match; running → unknown). `record_council_result`
   writes the result on cycle and candidate; failed/unknown block the program.
7. `write_report` and the event log; `status` is the store projection.

## Acceptance matrix → evidence

| Boundary | Test |
|---|---|
| Normal (two ticks, dedup, local + both live, ≤1 dispatch) | `test_two_ticks_dedup_select_once_capture_and_record_the_rejected_council` |
| Relevance/authority (ignored with reason, template immutable) | `test_relevance_is_deterministic_lexical_...`, `test_derived_manifest_keeps_goal_plan_budget_...` |
| Missing/error (unavailable ≠ empty; capture/council failure persisted) | `test_local_verification_failure_...`, `test_capture_failure_is_persisted_...`, `test_unknown_council_and_crash_after_row_...` |
| Budgets/time (headroom 7, deadline, caps persist, no retry) | `test_relevance_...` (headroom), `test_registration_is_immutable_and_counters_and_schedule_are_durable`, `test_ticks_stop_at_the_requested_cap_...` |
| Restart/concurrency (identical replay, exactly one claim, active unknown blocks) | `test_registration_...`, `test_concurrent_reservations_claim_exactly_one_cycle`, `test_postgres_reservation_claims_exactly_one_cycle` (skipped without `HARNESS_INTEGRATION=1`), `test_ticks_stop_...` (busy) |
| Git/cleanup (dirty checkout unchanged, only snapshot/ref, temp index removed) | `test_capture_commit_writes_only_the_snapshot_and_ref_and_leaves_the_checkout_alone` |
| Truth (rejected stays rejected; fixtures labelled; row is the authority) | `test_two_ticks_...`, `test_unknown_council_and_crash_after_row_...` |
| Reporting (counts from store, source errors visible, three categories, status without models) | `test_two_ticks_...`, `test_monitor_projection_is_additive_bounded_and_read_only`, CLI tests |
| Platforms | Linux run observed by the worker; Windows/CI are owner steps |

## Exact omissions and assumptions

- No live fetch, no real council, no real CallBudget ledger, no PostgreSQL run by the worker. The
  PG claim test exists but was skipped here (integration flag not set). The owner canary (two live
  ticks) and CI remain distinct unexecuted steps.
- `github_detail` is attempted once for a selected GitHub candidate; its absence/failure is
  recorded `unknown`, never success. GeekNews descriptions are discovery text only.
- The event log is an explicit local JSONL file (SPEC allowance); the observation schema is not
  changed and no observer event kinds were added.
- The runner is synchronous and installs nothing; an existing scheduled launcher may call
  `zeus research-program run ID --ticks N` on its own cadence. No launcher was modified.
- `MemoryStore` transactions are serialized by its lock; the concurrency test with threads is a
  unit-level control, not a separate-process PostgreSQL proof.
- `program_view` exposes local candidate repository-relative paths and the owner rationale is
  present only inside the Git-pinned capture (owner text), never in status, monitor or the report.
- Provider estimates (USD/seconds in SPEC) are not enforced by this code; the machine ledger and
  the template `claude` controls remain the enforced limits.
