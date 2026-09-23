# Durable Claude task sessions (INV-WORKER-SESSION-001)

2026-09-23. Batch "Next bounded implementation: durable Claude task sessions" of SPEC.md, base
fa7954caad5b95576dd65de81685f826650e2efd. Worker implementation evidence only: not independently
reviewed, not qualified against a real CLI, and not activated anywhere. The contract is
docs/contracts.md INV-WORKER-SESSION-001.

## Owners inspected and reused

| Owner | What it already did | Decision |
|---|---|---|
| `Executor._run` (adapters/executor.py) | reservation, unresolved-effect guard, provider entry, settlement, `service.checkpoint` with provider_session_id, workspace and policy/config digests | reused unchanged; an explicit `task_session` binding is threaded through the same reservation/entry/settlement path and adopted at a new `task_session` boundary before result persistence |
| `ClaudeCodeRuntime` (adapters/claude_cli.py) | `--session-id` per attempt, session/model agreement checks, terminal classification | extended: `session_home` + `task_session` restore/`--resume <id>`/export; every existing check stays |
| `IsolatedClaudeRuntime` + entry | disposable tmpfs `/home/worker`, removed after import; request protocols | extended with a session protocol pair, staging into the run's evidence mount and host re-verification |
| `Harness.checkpoint` / `sessions` bucket | last agent checkpoint per agent | unchanged; NOT treated as permission to open any session |
| `decisions_pending` rows | the executor's committed independent review decisions | read as the sole rejection/acceptance authority |
| `FileArtifacts` | content-addressed, integrity-checked text | reused for a separate restricted archive root |
| `providers.json` / invocation SUPPORT | Claude `session_resume: unsupported` | unchanged: native resume is conditional, not a capability flag |

New modules: domain/application/adapters `worker_sessions.py`; CLI `worker-session status|close`.
Not changed in the first batch (ecb0e6d6): `domain/observation.py`, `adapters/monitoring.py` (no
monitor source or structured transition; the CLI status was the only projection). The consolidated
correction below adds both. `service.py`, `providers.py`, `providers.json` remain unchanged.

## Consolidated correction (SPEC "Session primitive consolidated correction, 2026-09-23")

Retains the ecb0e6d6 implementation; one batch against the same matrix. Independent review must
cover the inherited primitive and this correction together.

| # | Finding (owner evidence) | Correction | Deciding test |
|---|---|---|---|
| 1 | `promote(task, sha256:000..0)` then `close` reached `closed` with no artifact (owner synthetic MemoryStore reproduction; `evidence=None` bypassed verification) | promotion and closure require a configured evidence store AND a receipt bound to this session/accepted candidate/archive/review, with every listed evidence ref and the review's execution receipt present intact; `close` re-verifies it; refusals leave the row unchanged; default close retains the archive | `test_promotion_and_closure_require_a_verified_receipt_bound_to_this_session`, `test_closed_only_after_promotion_...`, CLI test |
| 2 | same owner + changed model got a plan (owner synthetic reproduction) | compatibility checked before the duplicate-owner shortcut; refusal writes nothing | `test_duplicate_begin_by_the_owner_checks_compatibility_first_and_preserves_the_claim` (model, policy, image, config, runtime) |
| 3 | state transitions and monitoring projection omitted | Observer events after each committed change (`development.worker_session_transition`, `operations.worker_session_blocked`), fixed `next_owner`/`next_action`, additive `worker_sessions` monitoring source; binding only as `identity_sha256` | `test_committed_transitions_are_observed_once_...`, `test_monitoring_projects_session_states_...`, executor test (events on the real executor path), monitoring neighbour source-set tests |
| 4 | native Windows: entry test passed POSIX `HOME` to Windows `os.path.isabs`; two-turn, fake-container and executor fixtures failed; a short-path direct turn passed | entry test uses a HOME absolute on the executing platform and asserts `/home/worker` on POSIX (production entry unchanged); the three fixtures run under a short test-owned `tempfile.mkdtemp` root, removed afterwards (read-only Git objects made writable only inside it) | `short_root` teardown asserts the longest created path stays under 260 characters (Linux projects a 60-character Windows root) |

Item 4 is hypothesis-driven: the owner log was not available to this worker. Observation: under the
Linux projection the fake-container fixture's longest path (`<runs>/<32-hex run id>/evidence/
session-restore/projects/<host-derived key>/<session id>/tool-results/turn-1.txt`) projected 265
characters before its run root was shortened, i.e. MAX_PATH is reachable with pytest's longer
per-test directories. Hypothesis: the three Windows fixture failures are MAX_PATH. Unknown: the exact
Windows failure text; whether the host has long paths enabled. Production note (not changed): a real
container's key is `-workspace`, but the host-side evidence path of a deep session subdirectory under
a long Windows artifact root is bounded only by `MAX_ARCHIVE_DEPTH`; owner should confirm on Windows.

Not changed: production entry `HOME` check (real Linux container semantics), `providers.json`
capability, executor wiring (the host still constructs `WorkerSessions`; bootstrap does not).

## Acceptance matrix -> focused evidence (tests/test_worker_sessions.py)

| Matrix item | Test | Kind |
|---|---|---|
| fresh unchanged / default no-resume intact | `test_default_fresh_command_and_result_are_unchanged`, `test_executor_default_path_and_unsupported_combinations_refuse_before_entry` | fixture child |
| native resume uses exact archive/id, not latest | `test_two_turn_resume_restores_exact_archive_and_retains_history`, isolated test | fixture child; injected Docker + real entry |
| task/repository/model/policy mismatch | `test_foreign_task_...`, `test_model_or_policy_mismatch_...` | store |
| corruption / path escape / secret exclusion | `test_corrupt_or_missing_...`, `test_archive_with_valid_hash_...`, `test_manifest_refuses_...`, `test_export_excludes_...`, `test_restore_verifies_...` | real files |
| two owners race | `test_two_owners_race_for_one_logical_session` (controlled barrier) | store |
| duplicate checkpoint/review event | `test_duplicate_checkpoint_and_review_events_are_idempotent` | store |
| crash after archive write before PG commit | `test_crash_after_archive_write_before_store_commit_replays_once` | INJECTED crash |
| review wait uses no calls | `test_review_wait_holds_no_owner_and_makes_no_calls`, executor test (refused before entry, reservation abandoned, no child start) | store; executor |
| rejected candidate immutable | `test_rejected_candidate_is_immutable` | store |
| rejected correction retains prior history | two-turn tests (`prefix_verified`, reviews/candidates kept), `test_unproven_resume_continuity_...` | fixture child |
| cumulative usage not double-counted | `test_cumulative_usage_...`, executor test (settled totals 115 and 115, never 230) | executor + ledger |
| closed only after promotion; cleanup failure keeps bytes | `test_closed_only_after_promotion_...`, `test_promotion_and_closure_require_a_verified_receipt_...`, CLI test | store + real files + real FileArtifacts |
| duplicate begin identity | `test_duplicate_begin_by_the_owner_checks_compatibility_first_...` | store |
| observable transitions / monitoring | `test_committed_transitions_are_observed_once_...`, `test_monitoring_projects_...`, executor test | real Observer + MemorySpool; real collector; INJECTED store outage |
| Windows/POSIX paths | `test_windows_and_posix_workspace_keys_and_path_forms`, entry test, `short_root` path budget | pure; Linux projection only |
| real Claude | `test_real_claude_two_turn_resume_probe` | SKIPPED unless `ZEUS_REAL_CLAUDE_SESSION_PROBE` is set; owner only |

Store tests use MemoryStore only; no isolated PostgreSQL run of this module was made by the worker.

## Execution evidence

History (kept, not replayable by the inspector): candidate ecb0e6d6 reported checks whose argv began
with `timeout`; inspector 486d7c4d left 5 of 6 claims unexecuted solely for that prefix and showed no
test mismatch. Owner native Windows replay of the ten affected files: 226 passed, 29 skipped,
4 failed (session-owner-tests.log, not available to this worker). Neither is relabelled here.

Correction run, Linux container (this worker, 2026-09-23), plain commands without wrappers:

- `python -m pytest tests/test_worker_sessions.py -q -p no:cacheprovider`: 49 passed, 1 skipped
  (the owner-only real Claude probe).
- the twelve affected files (`test_worker_sessions`, `test_claude_assignment`,
  `test_claude_cli_process`, `test_claude_review_boundaries`, `test_claude_execution`,
  `test_isolated_worker`, `test_isolated_worker_preparation`, `test_isolated_project_evidence`,
  `test_executor`, `test_executor_research`, `test_monitoring`, `test_monitoring_observations`) in one
  command: 267 passed, 29 skipped (24 integration environment required, 3 Windows-only job object,
  1 owner Docker image check, 1 owner real Claude probe).
- `python -m ruff check . --no-cache`: passed.

Not run by the worker: native Windows, isolated PostgreSQL, the full repository suite, a real CLI or
image two-turn probe. Those are owner qualification; this is Linux evidence only.

## Unknowns the owner must qualify before production resume

- The pinned CLI's transcript location: this implementation assumes
  `$CLAUDE_CONFIG_DIR/projects/<cwd with every non-alphanumeric as '-'>/<session>.jsonl` plus the
  session's own subdirectory, and sets `CLAUDE_CONFIG_DIR` to the owned home. The fixture imitates
  that layout; it is not the real format.
- That `--resume <id>` in `--print` mode appends to the same transcript under the same session id
  (continuity is otherwise refused as `resume_continuity_unproven`, which is safe but blocks work).
- That the reported `usage` of a resumed headless turn is cumulative (the SPEC's reading of the docs).
- Combination with `--restricted` and the project-evidence protocol twin on a real image; a new
  worker image containing this entry is required (older entries refuse the session protocol).

Qualification: one real two-turn probe across a container recreation with a fixed-answer recall,
exported/restored bytes hashed, session and model agreement, then usage delta checked against the
raw totals. Record it as owner evidence; this document is not that evidence.

## Follow-ups (not in this batch)

Conductor continuation (sole admission owner of correction turns) consumes `begin`/`record_review`
and writes the promotion receipt (`promotion_receipt`) when it promotes accepted evidence; host
wiring of `WorkerSessions(evidence=..., observer=...)`; retention policy for archives after closure
(nothing here deletes an archive).
