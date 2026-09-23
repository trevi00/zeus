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
Not changed in this batch: `domain/observation.py`, `adapters/monitoring.py` (no monitor source or
structured transition yet; the CLI status is the only projection), `service.py`, `providers.py`.

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
| closed only after promotion; cleanup failure keeps bytes | `test_closed_only_after_promotion_...`, `test_promotion_verifies_...`, CLI test | store + real files |
| Windows/POSIX paths | `test_windows_and_posix_workspace_keys_and_path_forms` | pure |
| real Claude | `test_real_claude_two_turn_resume_probe` | SKIPPED unless `ZEUS_REAL_CLAUDE_SESSION_PROBE` is set; owner only |

Store tests use MemoryStore only; no isolated PostgreSQL run of this module was made by the worker.

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

Conductor continuation (sole admission owner of correction turns) consumes `begin`/`record_review`;
monitor source and structured observation transitions for session states; retention policy for
archives after closure (nothing here deletes an archive).
