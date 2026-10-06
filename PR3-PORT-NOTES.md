# PR-3 remainder port notes (G1-04b; temporary, removed before review)

Source WIP `c03bdc1c` (based on 0fa96de) ported onto main `b9d8f15` + batch a `16b47bc9`. Method: `git diff b9d8f15 c03bdc1c`
per path, applied hunk by hunk; every hunk that removes or changes a line main already has was inspected.

## Conflicts resolved (file: decision, reason)
- `domain/host_delivery.py`: main kept for both `classify_restart` hunks (S2R F1: the unconfirmed-start hold and the
  exact `request_at == requested` recognition) and its docstring. WIP taken for the additive `CREDENTIAL_*` constants,
  `validate_credential_evidence` and `__all__`.
- `adapters/host_delivery.py`: main kept for `self._launch(target, descriptor, {**context, "requested_at": ...})`.
  WIP taken (arm/bind contract requires it) for `MAINTAIN_PHASES`, the `--phase` help and `maintenance_controller`
  wiring (credentials, canary executor, qualification deadline).
  CHANGED vs WIP, per G1-03 ruling (c): the helper path/sha and the bound are read from the process environment of the
  invocation only (`_invocation_environment`), never from `_settings()` (which merges the persisted env file).
- `adapters/managed_runtime.py`: main kept (the only WIP hunk reverts the F1 `requested_at` stamping; no arm/bind hunk).
- `application/host_delivery.py`: WIP applied cleanly; its removed lines are only the restart-only docstrings/comments
  and the `maintain` phase refusal, which the arm/bind contract replaces. `release_queue.py`: identical in main, untouched.
- `adapters/maintenance_evidence.py`: WIP taken (additive; removals were restart-only docstring lines).
- `docs/contracts.md`: WIP hunks taken for the Fleet maintenance amendment, the ACTIVE-terminal paragraph, the S2R
  banner removal, the deployment-precondition/CLI/Tests text, the PR-2 observer sentence and the owner-actions armed
  paragraph. main kept for the INV-ROLE-CONTAINER-001 / INV-CODEX-CREDENTIAL-001 / INV-MONITOR-VIEWER-001 block (the
  WIP predates it), the blank line before the maintenance heading, and `test_fleet_maintenance_readiness.py` in the
  Tests list (the WIP deleted that file; it still exists and runs).
- `tests/host_delivery_maintenance_fixtures.py`: the WIP referenced `FakeMaintenanceFleet`/`FakeExecutor`, which it
  never defines. Wired to its own `LossyFleet` (the REAL Fleet with batch a's permit API), a `ScriptedLauncher` and the
  REAL `MaintenanceCanaryExecutor` (`RecordingExecutor`; real-time wait capped at 0.3 s for a never-finishing job).
  `owner_requests` enqueues a REAL queued Fleet job for the canary. Main kept: `registered_fleet`, `hold_activation`,
  `hold_unit` and their exports (the WIP dropped them from `__all__`).
- `tests/test_host_delivery_maintenance.py`: main kept for `unpause` and the three Fleet applicability rows
  (`fleet not owner-paused`, `activation hold`, `held unit`; the WIP replaced them by attribute pokes on its undefined
  fake). WIP taken, as the arm/bind contract requires: `effects()` (adds fleet/executor), the check-mode test (arm/bind
  no longer refuse `maintenance_phase`), the txn-nesting test (also arms) and the PR-2 observer test (extended past
  bind; its original two assertions are unchanged). All arm/bind tests added.
- `tests/test_host_delivery_maintenance_domain.py`, `_adapter.py`: main kept for every F1 test/case (the WIP removed
  them); only additive domain tests taken.
- `tests/test_host_delivery_maintenance_guards.py`: main kept for the two restart tests; the WIP variants (failed after
  arm, armed-intent old-controller hazard) are added as NEW tests.
- `tests/test_host_delivery_maintenance_cli.py`: WIP taken where the contract changed the CLI (arm/bind accepted, ports
  built); the controller-wiring test changed per ruling (c) and asserts a persisted-config value is ignored.
- `tests/test_host_delivery_maintenance_e2e.py`: WIP taken: the restart-only e2e asserted `arm`/`bind` refuse
  `maintenance_phase`, which the contract reverses; it is replaced by the restart+arm+bind e2e (restart steps unchanged).
- Restart-phase tests that stay byte-identical: every other test in those files (domain `CLASSIFY_CASES`, adapter F1
  launch tests, `test_restart_*`, applicability rows) passes unchanged.

## S2M coverage (covering test per row; S2M-1..8 unchanged and still passing)
- S2M-9: `test_arm_refuses_before_started_and_without_verified_primary`, `test_arm_requests_grants_acknowledges_then_arms_one_deadline`,
  `test_a_window_beyond_the_qualification_deadline_is_refused` (bound supplied+exceeded; and bound-unset path: the
  600 s window alone, in `test_arm_requests_...` / `test_unchanged_owner_actions_...`), `test_expiry_before_admission_...`,
  `test_failure_never_rolls_back_...` (changed instance), `test_lost_control_...` (replayed arm: `maintenance_already_used`).
- S2M-10 (mapped, not required here): `test_unchanged_owner_actions_owe_exactly_one_new_instance_canary`.
- S2M-14: `test_bind_binds_only_the_genuine_new_instance_receipt`, `test_bind_refuses_every_unbound_receipt[...]`,
  `test_a_rejected_or_changed_canary_fails_the_generation_without_rollback`.
- S2M-15: `test_bind_replay_cached_drift_refused_history_kept_settlement_held`.
- S2M-16: `test_failure_never_rolls_back_resets_supersedes_or_consumes_twice`, `test_a_canary_that_settles_after_the_deadline_fails_without_binding_or_rollback` (critique #1, new), `test_failure_after_arm...` guards test.
- S2M-17: `test_check_mode_has_zero_effects_across_phases`, cli `test_check_builds_no_observer_git_executor_or_artifact_store`.
- S2M-18: `test_one_active_generation_is_restarted_armed_and_bound_end_to_end` (target-file provenance, PR-2 predicates),
  `test_pr2_observer_refuses_during_maintenance_and_accepts_after_bind`.
- S2M-11/12/13 (Fleet side, batch a) + arm side: `test_lost_control_or_lane_acknowledgements_and_two_arms_spawn_once`,
  `test_an_unknown_dispatch_is_never_executed_again`, `test_admitted_reserving_job_is_never_expired`.
