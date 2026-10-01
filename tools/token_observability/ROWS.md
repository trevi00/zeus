# W1 row table (ACCEPTANCE A01-A59)

W1a = accepted at cbb5f53; W1b = the second work item; W1c = the round-1 corrections F1-F6 (REVIEW-W1-r1); W2 = deployment files, dashboards, rules, runbook; n/a = not a W1 test.
Files: `tests/token_observability/test_tokobs_<s1_lifecycle|streams|partition|render|s2|codex|windows|backfill|serve|golden|dashboards|w1c>.py`.

| Row | Phase | Test(s) |
|---|---|---|
| A01-A11, A19, A31, A40, A44 | W1a | s1_lifecycle: `test_a01`…`test_a11`, `test_a19`, `test_a31`, `test_a40`, `test_a44` (A44 lane metadata: s2 `test_lane_metadata_finished_is_terminal_evidence_and_a_late_one_is_a_correction`) |
| A12-A16, A48 | W1a | streams: `test_a12`…`test_a16`, `test_a48` |
| A17 | W1a + W1b | streams `test_a17_concurrent_streams…`; s2 `test_a17_two_routine_attempts_and_a_coordinator_stream_grow_together` |
| A18 | W1a + W1b | streams `test_a18_second_collector…`; serve `test_a18_a_second_serve…` |
| A20, A21 | W1b | codex `test_a20_…`, `test_a21_…` (+ `test_c_w1_4_…`, `test_c_w1_3_…`) |
| A22, A34-A38, A42 | W1a | partition `test_a22`, `test_a34`…`test_a38`, `test_a42` |
| A23, A24 | W1a | render `test_a23_roots_validate_on_any_platform`, `test_a24_no_text_no_ids_and_every_label_is_bounded` |
| A54 | W1c | dashboards `test_a54_*` lint `dashboards/provider-windows.json` (static panel mapping only; the collector's one-hot state tests in windows are not dashboard evidence) |
| A25-A30, A55-A57 | W2 | not in this item (rules, dashboards, compose, runbook, connectivity) |
| A32, A33 | W1b | backfill `test_a32_*`, `test_a33_deferred_rows_are_counted_but_never_ingested` (the §3.10 common-ID `shadow` variant is a future fixture, not ingested in phase 1) |
| A39 | W1a | s1_lifecycle `test_a03_a39_…` |
| A41 | W1a (S1) + W1b (S2) | s1_lifecycle `test_c_w1_1_a41_…`; s2 `test_a41_coordinator_without_metadata_…`, `test_a41_lane_with_metadata_still_started_…` |
| A43 | W1a (render) + W1b (serve) | render `test_a43_render_refusal_…`; serve `test_a43_render_refusal_keeps_the_last_good_data_and_serves_the_refusal` (`TokObsRenderRefused` rule test is W2) |
| A45 | W1a | s1_lifecycle `test_a05_a45_…` |
| A46 | W1b | codex `test_a46_…` |
| A47 | W1a (routine) + W1b (Codex) | streams `test_a47_copied_stream_…`; codex `test_a47_codex_copy_…` |
| A49 | W1b | codex `test_a49_…` |
| A50-A53 | W1b | windows `test_a50_*`, `test_a51_*`, `test_a52_i/ii/iii_*`, `test_a53_i_*`, `test_a53_ii_*` |
| A58 | W1a (routine) + W1b (coordinator, Codex) | streams `test_a58_*`; s2 `test_a58_coordinator_torn_tail_…`; codex `test_a58_codex_torn_tail_…` |
| A59 | W1b | codex `test_a59a_…`, `test_a59b_…` |
| C-W1-1 | W1a | s1_lifecycle `test_c_w1_1_*` |
| C-W1-2 | W1b | s2 `test_c_w1_2_*`, `test_unnamed_coordinator_stream_…`; codex `test_a59b_…` |
| C-W1-3 … C-W1-7 | W1b | codex `test_c_w1_3_*`, `test_c_w1_4_*`; backfill `test_c_w1_5_*`, `test_c_w1_7_*`; s2 lane/coordinator continuity tests (C-W1-6) |
| goldens | W1b | golden `test_scenario_matches_its_goldens[routine|s2_windows|codex]` |

## W1b limits
- Coordinator and lane-without-mode streams: continuity per C-W1-6 (fresh lane baseline 0; coordinator M only).
- Late facts (F4): a Codex horizon-finalized run's later terminal line is a `late_terminal` correction (kept next to the
  `late_tail` growth fact); `report --invocation <id|stem>` shows a Codex run, lane or coordinator stream without a task
  binding, with its late facts and the refined or still-unknown allocation. A late result is never a published contribution.
- Idle horizons use mtime (delay only, §3.1); Codex idle = 2 x `POLICY.decision_seconds` read by `vocab.codex_idle_seconds()` (C-W1-8).
- Ingest lag = now minus the previous successful scan. Backfill for S2/S3 (F5, REVIEW-W1-r2) = a source-supported
  terminal timestamp before `live_since` (a lane's own `finished_at`), or the source's unavailability horizon already
  satisfied AT `live_since`. Terminal presence is not terminal age; a stream's mtime is an idle measure only and never a
  completion time. A finished stream with no earlier terminal-time evidence (a Codex line carries none) stays live
  inside the horizon: a disclosed limit (§3.9), not a back-dated timestamp.
- Review rounds: no source exists (C-W1-5); `<stem>-codex-prestart.json` is a W2 allowlist item (C-W1-4).
- Real Codex lines carry `cache_write_input_tokens` (always 0); a point lacking it leaves `cache_write` unknown (C-W1-3).
- Read bound: `MAX_READ_BYTES` is the nominal chunk. A single line longer than the chunk is held whole (`_read_chunk`
  extends to a newline; `_first_line_hash` reads one line), so memory is the chunk plus the longest line. No new numeric
  limit is invented; the resource-bound validation is W2's.
- Serve cadence is DESIGN's 30 s (`serve.SCAN_INTERVAL_SECONDS`).

## Round-1 corrections (REVIEW-W1-r1 F1-F6); every test in `test_tokobs_w1c.py` unless noted

| Finding | Change | Tests |
|---|---|---|
| F1 | migration 3 `alias_state` (init session/model, Codex thread per read alias, written with the offset); unbound Claude id = `session:uuid\|unbound\|type`, no model label | `test_f1_a_claude_alias_split_across_scans_…`, `test_f1_the_split_result_is_read_in_bounded_chunks_…`, `test_f1_two_unbound_copies_with_different_provisional_labels_…`, `test_f1_a_new_read_identity_does_not_inherit_…`, `test_f1_canonical_arrival_after_a_split_alias_…`, `test_f1_a_codex_alias_split_after_thread_started_…` |
| F2 | `partition.NESTED_*` tri-state (`results.nested` 0 none / 1 present / 2 unknown); exclusive `advisor` only on explicit zero/zero | `test_f2_exclusive_advisor_needs_explicit_zero_nested_counters` (6 cases), `test_f2_no_consultation_…`, `test_f2_one_result_without_the_zero_evidence_…` |
| F3 | `vocab.version_semantics` (+ `CHARACTERIZED_FAMILIES`); an uncharacterized major/minor is M only + `unknown_version_semantics` | `test_f3_an_uncharacterized_major_or_minor_…` (3), `test_f3_a_supported_version_…`, `test_f3_one_policy_…` |
| F4 | migration 4 (`late_results`, `late_result_models`, `late_codex_terminal`, `corrections.linked_ref`); `late.py`; Codex `late_terminal`; linked `late_predecessor`/`late_point`; `report --invocation` | `test_f4_a_predecessor_arriving_…`, `test_f4_a_late_predecessor_that_still_cannot_refine_…`, `test_f4_late_results_without_numbers_…`, `test_f4_a_codex_terminal_after_the_horizon_…`, `test_f4_a_codex_failed_terminal_…`, `test_f4_a_late_codex_point_…`, `test_f4_report_cli_…`, `test_f4_a_lane_predecessor_discovered_…` |
| F5 | `backfill.stream_is_history(terminal=, horizon_seconds=)`; S3 `has_terminal_line` (superseded by round 2); the mtime-only test is replaced | backfill `test_a32_streams_that_had_ended_before_live_since_are_history`, `test_a32_lane_with_finished_metadata_…`, `test_f5_*` (3) |
| F6 | `dashboards/provider-windows.json` + lint | dashboards `test_a54_*` (5) |
| nonblocking | serve cadence 30 s; per-line read bound stated in the `s1_routine` docstring and above | `test_serve_scan_cadence_is_the_designs_30_seconds` |
