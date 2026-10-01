# W1 row table (ACCEPTANCE A01-A59)

W1a = accepted at cbb5f53; W1b = this work item; W2 = deployment files, dashboards, rules, runbook; n/a = not a W1 test.
Files: `tests/token_observability/test_tokobs_<s1_lifecycle|streams|partition|render|s2|codex|windows|backfill|serve|golden>.py`.

| Row | Phase | Test(s) |
|---|---|---|
| A01-A11, A19, A31, A40, A44 | W1a | s1_lifecycle: `test_a01`…`test_a11`, `test_a19`, `test_a31`, `test_a40`, `test_a44` (A44 lane metadata: s2 `test_lane_metadata_finished_is_terminal_evidence_and_a_late_one_is_a_correction`) |
| A12-A16, A48 | W1a | streams: `test_a12`…`test_a16`, `test_a48` |
| A17 | W1a + W1b | streams `test_a17_concurrent_streams…`; s2 `test_a17_two_routine_attempts_and_a_coordinator_stream_grow_together` |
| A18 | W1a + W1b | streams `test_a18_second_collector…`; serve `test_a18_a_second_serve…` |
| A20, A21 | W1b | codex `test_a20_…`, `test_a21_…` (+ `test_c_w1_4_…`, `test_c_w1_3_…`) |
| A22, A34-A38, A42 | W1a | partition `test_a22`, `test_a34`…`test_a38`, `test_a42` |
| A23, A24 | W1a | render `test_a23_roots_validate_on_any_platform`, `test_a24_no_text_no_ids_and_every_label_is_bounded` |
| A25-A30, A54-A57 | W2 | not in this item (rules, dashboards, compose, runbook, connectivity) |
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
- `late_terminal` is not detected for Codex runs (only `late_tail`); `report --task` does not show Codex late points.
- Idle horizons use mtime (delay only, §3.1); Codex idle = 2 x `POLICY.decision_seconds` read by `vocab.codex_idle_seconds()` (C-W1-8; was mirrored in `vocab.CODEX_IDLE_SECONDS`, guarded by a policy test.
- Ingest lag = now minus the previous successful scan; backfill for S2/S3 = stream last written before `live_since`.
- Review rounds: no source exists (C-W1-5); `<stem>-codex-prestart.json` is a W2 allowlist item (C-W1-4).
- Real Codex lines carry `cache_write_input_tokens` (always 0); a point lacking it leaves `cache_write` unknown (C-W1-3).
