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
| A25-A30, A55-A57 | W2 | W2a below (files, linter, static tests); dashboards, runbook and the A56 connectivity test are W2b |
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

## Round-2 closure (REVIEW-W1-r2, final prescription F4/F5); each assertion → passing test

F4 (`test_tokobs_w1c.py`; `late._baseline_models` returns the proof state, `unproven` when any ordinary `results` or
`late_results` row of the predecessor is zeroed, passed through the shared `resumed_baseline`):

| Prescription assertion | Test |
|---|---|
| Executed late success(100) → zeroed error, successor cumulative 150, M 20: `still_unknown`, `no_baseline`, remainder `[]`; late facts and link kept; published rows unchanged; replay adds no correction | `test_f4_a_late_predecessor_with_a_zeroed_result_keeps_the_zeroed_crash_refusal` |
| Order does not matter (zeroed then nonzero late result) | `test_f4_a_zeroed_late_result_alone_is_not_a_proven_baseline_either` |
| Zeroed ordinary predecessor with later correction link: `still_unknown`/`no_baseline`, `[]` | `test_f4_a_zeroed_ordinary_predecessor_discovered_later_with_correction_facts_is_still_unknown` |
| Positive control: successful late predecessor still reports remainder 30 (150 − 100 − M 20); lane control 4 | `test_f4_a_predecessor_arriving_after_the_successor_finalized_is_a_linked_late_predecessor`, `test_f4_a_lane_predecessor_discovered_after_the_successor_finalized_is_a_late_predecessor` |
| Unknown-version and restart rules unchanged | `test_f4_a_late_predecessor_that_still_cannot_refine_reports_still_unknown` |

F5 (`test_tokobs_backfill.py`; `backfill.stream_is_history(terminal_at=, horizon_seconds=)`; lane `finished_at`
is the only source-supported terminal timestamp, Codex lines carry none):

| Prescription assertion | Test | Synthetic totals (live output / backfill count) |
|---|---|---|
| Old stream bytes + post-cutoff completion metadata → live | `test_f5_old_stream_bytes_with_post_cutoff_completion_metadata_stay_live` | 100 / 0 |
| Delayed discovery, terminal time unavailable, inside the horizon → live (and stays live on a later scan) | `test_f5_delayed_discovery_with_unavailable_terminal_time_inside_the_horizon_is_live`, `test_f5_a_codex_terminal_line_inside_the_horizon_has_no_terminal_time_and_stays_live` | 100 / 0; 4 / 0 |
| Supported pre-cutoff terminal timestamp → history | `test_a32_lane_with_a_supported_pre_cutoff_terminal_timestamp_is_history` | 0 / 1 |
| Horizon expired before the cutoff → history | `test_f5_a_horizon_already_expired_at_the_cutoff_is_history_without_a_terminal_timestamp`, `test_f5_a_codex_run_whose_idle_horizon_had_expired_at_first_start_is_history`, `test_a32_streams_that_had_ended_before_live_since_are_history` | 0 / 1; 0 / 1; 0 / 2 |
| Controls kept: active S2/S3 and restart, routine A32, outage catch-up | `test_f5_an_active_coordinator_…`, `test_f5_an_active_codex_run_…`, `test_a32_evidence_older_than_live_since_…`, `test_a32_an_attempt_still_in_flight_…`, `test_a32_outage_catch_up_…` | unchanged |

## W2a (deployment files, deploy linter, static lint tests)

Files: `deploy/observability/**`, `tools/token_observability/tokobs/deploy_lint.py` (+ `lint-deploy` in `__main__.py`),
`tests/token_observability/test_tokobs_deploy.py`. Owner-run checks are **NOT run in this pilot**: `docker compose config`,
`promtool check config/rules`, `promtool test rules`, any Docker run.

| Row | Test or file | Status |
|---|---|---|
| A55 compose structure | deploy tests `test_a55_networks_and_volumes`, `…_every_service_is_hardened_and_limited`, `…_networks_and_ports_per_service`, `…_collector_mounts_are_exactly_the_five_inputs`, `…_the_secret_path_appears_only_in_grafana`, `…_prometheus_service`, `…_grafana_service`, `…_every_bind_source_in_the_checkout_exists` | pytest |
| A55 provisioning | `test_a55_prometheus_and_grafana_provisioning_are_static_and_consistent` (scrape target, datasource URL, rule/dashboard paths equal the mount targets, `allowUiUpdates` false) | pytest |
| A55 conntest override | `test_a55_the_conntest_override_mounts_no_worker_input` (`!override` loaded by a SafeLoader subclass) | pytest |
| A57 compose | `test_a57_the_production_compose_file_has_no_violations`, `…_each_denied_compose_configuration_is_rejected_with_exactly_its_violation[13 cases]`, `…_short_syntax_ports_are_parsed`, `…_the_normalized_long_syntax_form_passes_and_its_mutations_fail` | pytest |
| A57 docker inspect, CLI | `test_a57_a_hardened_inspect_list_has_no_violations`, `…_each_denied_inspect_field_…[16 cases]`, `test_a57_cli_exit_codes`, `…_cli_reads_stdin_for_a_dash` | pytest |
| A57 read allowlist | `test_a57_allowed_input_matches_segment_by_segment`; `test_a57_the_collector_opens_only_allowlisted_paths_decoys_never` (audit hook over one real `Service.scan_now`: every allowlist kind opened, 7 decoys and `other.json` never; the prestart sidecar opened) | pytest |
| A27 / A28 rules part | `test_a27_no_rule_combines_…`, `test_a28_no_charge_or_bill_metric_…`, `test_the_rule_file_matches_design_5_1` (dashboard part is W2b) | pytest |
| A25, A26, A43, A29 | `deploy/observability/prometheus/rules/tokobs.test.yml` (A25 exporter-down and scan-stale, A26 ratio 0.25 + alert, A43 render-refused, A29 `ignoring(token_type) group_left` join) | owner-run: promtool — NOT run in this pilot |
| A29 static config | `docker compose config`, `promtool check config`, `promtool check rules` | owner-run: promtool / docker compose config — NOT run in this pilot |

## W2b (dashboards, runbook, A56 connectivity test)

Files: `deploy/observability/grafana/dashboards/{zeus-llm-usage,zeus-tokobs-health}.json`, `docs/observability/RUNBOOK.md`,
`tests/token_observability/test_tokobs_{dashboards_w2,runbook,conntest}.py`. `provider-windows.json` stays in
`tools/token_observability/dashboards/` (A54, not provisioned); the usage dashboard embeds its four panels verbatim.
The recording rule is DESIGN §5.1's `zeus:llm_unknown_ratio:1d` (EFFICIENCY §2's `…usage_unknown_ratio…` is a slip).

| Row | Test or file | Status |
|---|---|---|
| A25 panels show No data, not 0 | `test_a25_no_vector_zero_and_no_numeric_novalue`, `test_a25_every_data_quality_panel_says_no_data` (dashboards_w2) | pytest |
| A25 rules (exporter down, scan stale) | `deploy/observability/prometheus/rules/tokobs.test.yml` | owner-run: promtool — NOT run in this pilot |
| A26 | `tokobs.test.yml` | owner-run: promtool |
| A27 dashboards | `test_a27_no_expression_combines_a_provider_metric_with_a_token_metric`, `test_a27_the_provider_window_panels_equal_provider_windows_json` | pytest |
| A28 dashboards | `test_a28_cost_panels_are_titled_as_estimates_and_nothing_says_charge_or_bill` | pytest |
| A29 (dashboards part) | `test_every_expression_uses_a_rendered_metric_a_recording_rule_or_up`, `test_dashboard_identity_and_datasource`, `test_usage_variables_…`, `test_usage_rows_follow_design_section_6_order`, `test_dashboards_directory_holds_exactly_the_two_provisioned_files`; always-visible shares: `test_the_unattributed_and_ambiguous_shares_are_always_visible` | pytest; `docker compose config` / `promtool check` stay owner-run |
| A30 isolated cleanup | `test_tokobs_runbook.py` (`test_a30_*`, 7 tests over the fenced blocks of RUNBOOK.md) | pytest |
| A54 | `test_tokobs_dashboards.py` (W1c) | pytest; the same panels are re-linted inside the usage dashboard by A27 |
| A55 | W2a deploy tests; the conntest step 3 re-checks the resolved config | pytest / owner-run |
| A56 connectivity | `test_tokobs_conntest.py::test_a56_isolated_connectivity` (12 named steps) | owner-run: needs Docker, `TOKOBS_CONNTEST=1`; skipped by default, NOT run in this pilot |
| A57 | W2a deploy tests; conntest steps 3 and 10 reuse `lint_compose`/`lint_inspect` | pytest / owner-run |
