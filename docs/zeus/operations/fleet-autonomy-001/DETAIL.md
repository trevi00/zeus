# fleet-autonomy-001 routing slice — implementable detail

Specification refinement only; no approval, implementation, tests, model calls or operations performed. Latest `CLAUDE-CODEX-ROLES.md` read first. Claude owns design/scope. This supplements the draft `docs/zeus/operations/fleet-autonomy-001/SPEC.md`; it does not edit that draft. Earlier R1–R4 are narrowed by the draft’s explicit exclusions (detail-worker routing, enablement, visual work and real calls).

Code citations below are relative to `src/codex_harness/` at main `d049c478c25fe1c9338b8194ee6b81ef3fe9d43f`. Read through review HEAD `5eb16c1`; `git diff --stat 5eb16c1 d049c47` was empty. Test paths are repo-relative. Do not read the author’s later dirty changes as this baseline.

## 1. Exact edit sites and implementation shape

### Policy and selection

- `resources/providers.json:43–93`: put `read_only_runtime` **beside** `runtime` under `providers.claude`, not inside base runtime and not in an assignment. Leave writable runtime bytes, worker rule and default provider unchanged. Add the exact eight read-only pairs in SPEC (six dge_role identities, frontdesk, plan) after the existing writable rule at95–109. `lead:researcher/dge_role` also serves v2’s unchanged packet author, not just v1.
- `domain/providers.py:44–55,124–129`: add an optional Provider field for the overlay and parse/validate it. Missing is backward-compatible; a present null/empty/malformed object must not mean “absent.” Current runtime parsing only checks dict type, so it does not enforce the new contract itself.
- One shared domain validation helper should serve policy parsing and transport preflight. Require exact declared keys, lists of nonempty exact tool-name strings (not `Read(*)`, wildcard, or arbitrary coercible values), nonempty `tools`/`allowed_tools` subsets of `{Read,Glob,Grep}`, `allowed_tools` contained in tools, required deny names, and the exact selected mode below. Extra deny names are fine. Refuse a read-only Claude assignment without a valid overlay while parsing assignment rules (`:134–153`).
- `select_execution`, `domain/providers.py:303–326`: after choosing/validating the enabled pair, copy base runtime then overlay for read-only only; retain subscription accounting injection. No in-place mutation of Provider.runtime and no host/model-output override of the overlay. `ExecutionAssignment.receipt` at283–293: conditionally add a bounded profile-applied marker and profile digest for read-only overlay executions. Omit them on writable runs to preserve their receipt shape. Policy/config digests already bind changed packaged bytes.

### Claude preflight, argv/settings and streaming

- `adapters/claude_cli.py:337–346`: replace unconditional read-only refusal with shared profile validation, **before any spawned process**. Validate the effective runtime, not an asserted `validated=True` marker. Direct runtime construction must not bypass it.
- `claude_settings` at120–133 builds `permissions.allow/deny/defaultMode`. `_planned_flags` at241–263 and `_command` at288–334 supply `--tools`, `--permission-mode`, `--permission-prompts`, `--strict-mcp-config`, `--setting-sources`, optional `--restricted` and hashed `--settings`. Keep settings redaction. Validate final `_run_settings` output (270–286, invoked384) too: caller-provided settings or worker/project profile merging can add Bash grants/hooks even when the runtime lists look safe. For this slice refuse incompatible worker_profile/project_delivery/task-session or added settings rather than inventing a read-only variant of the implementation profile. Normal design callers do not attach those profiles (`executor.py:387–403`, profiled only when action implement).
- Tool-name observation is already normalized: `_normalize_message`, `claude_cli.py:865–881`, emits `type="tool_started"`, `tool=<name>`. The event loop at472–489 sees every normalized event **before retention limits**. Check names there or in `_StreamState.observe`; do not depend on retained events or `started_tools`, which only stores IDs (`:772–773`). Check even missing IDs/names. A tool outside the selected profile’s allowed names, including a missing name, latches a violation for the run. Stop through the existing termination/finally path and retain the violation even if a success terminal was already seen or appears later. Existing output-loss/unknown-cleanup handling must remain fail-closed.
- Keep OUTCOMES unchanged (`domain/invocation.py:35–36`). Represent this as existing `provider_failure`, with fixed diagnostic code `read_only_violation` (e.g. failure cause `claude-provider-read-only-violation`, reason_code `read_only_violation`). Set answer None. Return a structured failure before `_result` decodes/accepts an answer (`claude_cli.py:633–655`); give the latched violation precedence over missing-terminal caused by stopping the child. Retain independent unknown-cleanup/stream-loss facts. Never echo arbitrary tool payloads into outward diagnostics.
- `domain/invocation.py:106–120` already classifies a failure as provider_failure; `executor.py:974–996` settles the invocation; `:1015–1027` persists evidence; `adapters/execution_output.py:120–137` raises ExecutionFailure after writing it. Use this path, not a post-spawn bare ContractError that abandons the normal receipt, and not a new OUTCOMES member. Add a narrow executor integration test proving no succeeded task/downstream assignment is created.
- `domain/invocation.py:29`: mark read_only supported only with the above transport guard. Static support means the transport can enforce its profile condition, **not** that every runtime/profile/backend is eligible or every actual call has been qualified. Metadata effects for read_only=False also change, as noted below.

### Call sites

- `adapters/executor.py:1192–1203`: actual plan branch calls `_run(agent,... PLAN,True,... workload="design")`; add `action="plan"` here only. Workflow sender is conductor and recipient is `lead:improvement` (also exercised in `tests/test_model_routing.py:95–100`). Do not tag every decision or every lead action as plan.
- Council `adapters/autonomous_roles.py:342–363`: existing action dge_role, workload design, read_only True; agent validated against role mapping; unchanged-HEAD/clean-tree checks retained. No call-site edit needed. `domain/model.py:94–104` limits conductor self-assignment to dge_role with details.role conductor; `domain/council.py:51–64` and `adapters/autonomous_roles.py:215` give it design arbitration. This is not the ordinary conductor review phase; do not generalize its permission to reviews.
- Front Desk `adapters/frontdesk.py:283–288`: already action frontdesk, workload design, True, max_handoffs1 with before/after clean-checkout checks. No execution call-site edit needed.
- Review/diagnosis `executor.py:1557–1569` keeps action None and its current model. DBA/attacker, research workers and unlisted actions gain no rule. Wrong workload/read_only for an **enabled** pair must refuse; it must not silently fall back to Codex.

## 2. Permission mode: installed evidence and bounded meaning

Read-only commands executed here: `/home/trevi/.local/bin/claude --version` → **2.1.280 (Claude Code)**; `/home/trevi/.local/bin/claude --help` lists `acceptEdits, auto, bypassPermissions, manual, dontAsk, plan`. It says `--permission-prompts none` automatically denies anything that would prompt and says `--tools` selects available built-ins. No model invocation occurred.

Use **`permission_mode: "dontAsk"`** for this noninteractive allowlisted slice, plus existing `permission_prompts:"none"`. Validate that exact value; “anything except acceptEdits/bypassPermissions” wrongly accepts unknown values and mode auto. The mode alone is not the read-only guarantee: explicit tool exposure + allow/deny + stream failure and existing checkout checks are the mechanism. CLI help confirms availability; it does not independently prove filesystem effects.

**Precise draft amendment needed:** base runtime is `restricted:false` (`providers.json:52`), while the draft calls this a “validated restricted profile” and permits only four overlay keys. If “restricted” means CLI `--restricted`, add fifth overlay key `restricted:true`, validate exact boolean True, and leave base false. This is the smallest coherent reading; help says restricted confines file tools to working directories and ignores user/project/local settings, but managed settings still apply. Do not silently claim restricted execution while passing no flag. Preserve the later real-call qualification as explicitly out of scope; fixture evidence is not a production proof or general OS sandbox guarantee.

## 3. Exact affected tests and finite additions

Existing expectation edits (not wholesale test rewrites):

| Test | Exact adjustment |
|---|---|
| `tests/test_claude_assignment.py:32` `test_the_packaged_policy_defaults_to_codex_and_permits_one_pairing` | Replace exact one-pair set with exact existing writable + eight new pairs; retain wrong-workload/read-only negatives. |
| same file:75 `test_a_pairing_the_packaged_policy_does_not_permit_refuses_the_configuration` | Remove plan from list of forbidden pairs; replace with genuinely forbidden DBA/attacker/review pair. |
| `tests/test_claude_cli_process.py:295` `test_the_request_matrix_refuses_what_this_transport_cannot_prove` | parse_request True no longer rejected; invalid effective runtime still rejected pre-spawn. `unconfirmed` becomes empty and `effect_verified_here` gains read_only even for False. Unsupported session_resume remains. |
| `tests/test_claude_execution.py:426` `test_the_reservation_records_which_option_effects_were_verified_here` | Same two metadata assertion changes at434/436. This is an intentional receipt metadata delta, not writable execution change. |

No literal packaged providers.json SHA256 expected value was found in the searched tests: policy/config digests are generated and checked nonempty, not hardcoded. Do **not** rewrite historical manifests/evidence digests. Guard tests that should stay unchanged: `test_claude_cli_process.py:385` base restricted remains false; `test_claude_review_boundaries.py:256` experiment ceilings unchanged; `test_subscription_accounting.py:231–234` writable runtime equals base; `test_operation_cli.py:67` implementation worker_profile/restricted stays as before. `tests/test_worker_profile.py` writable hooks and metadata remain unchanged. Listing every file importing packaged_policy is not a list of tests requiring changes.

Add these cases in existing modules (suggested exact names):

- **Row1**, `test_claude_assignment.py`: `test_read_only_overlay_is_strict_and_required_for_read_only_rules` parametrizes missing/extra keys, null, wrong types, empty tools, Bash/Edit/Write/NotebookEdit exposure, wildcard, missing denies, mode auto/unknown/acceptEdits/bypassPermissions; every invalid policy refuses. `test_read_only_overlay_is_copy_only_and_receipted` asserts applied digest/marker and unchanged writable runtime/receipts.
- **Row1**, `test_claude_cli_process.py`: `test_read_only_rejects_unrestricted_or_conflicting_effective_settings_before_spawn`; `test_read_only_allowed_tools_complete_with_restricted_argv`; `test_read_only_tool_violation_survives_success_terminal_and_event_retention`. Parameterize forbidden tool names (including Task, MCP, unknown/missing name and missing ID), subset mismatch, success before/after forbidden event, and retained_events too small. Assert failure code, classify_result provider_failure, answer None, confirmed cleanup, no falsely accepted result. Read/Glob/Grep positive fixture records exact argv/settings and applied profile metadata.
- Reuse **`tests/claude_protocol_child.py`**, named by `test_claude_cli_process.py:20–45`, not a new subprocess harness. `tool_round` at64–70 currently always emits Edit; normal scenario185–195 uses it. Preserve default behavior for all old tests; add dedicated read-only scenarios or optional tool name. `transport` currently hardcodes RUNTIME/settings; extend with optional explicit runtime override, retaining old defaults. Stub writes observation/trace files itself: label them fixture instrumentation, never proof of no real filesystem writes.
- **Row1/3**, `test_claude_execution.py`: `test_read_only_violation_is_persisted_and_never_completes_task` uses existing build/runtime-factory fixture at53–69; enable permitted design pair, inject forbidden stream, assert invocation settled provider_failure, receipt diagnostic retained, task not succeeded/no implementation outbox. Clean read-only plan positive path asserts no profile/project Bash grants.
- **Row2**, `test_claude_assignment.py`: `test_design_read_only_assignment_matrix` covers each eight-pair row: disabled→Codex; enabled+design+True→Claude; enabled wrong flags→refusal; DBA/attacker/frontdesk wrong action/reviews/diagnosis/research workers unenabled→Codex; explicitly enabling unlisted→parse refusal. v2 improvement alternative stays Claude despite internal attacker slot. Keep worker implementation positive/negative controls.
- **Row3**, `tests/test_model_routing.py`: extend the actual plan workflow test at73–100 or add `test_plan_passes_trusted_action_and_keeps_review_default` to capture action plan, True/design; following implementation unchanged; decision action None remains Codex. Existing `tests/test_council_roles.py`, `tests/test_autonomous_roles.py`, and `tests/test_frontdesk.py:730` protect current call flags and checkout checks without gratuitous edits.

## 4. Material draft corrections / reachable boundaries

1. **Restricted profile ambiguity**: base false + four-key overlay never emits --restricted. Apply the precise fifth-key amendment above, or explicitly remove the CLI-restricted claim. Do not leave these contradictory.
2. **Selection expectation is too broad**: SPEC §4.2 says final_validation selects Codex. With a host-enabled design pair but mismatched workload, `domain/providers.py:303–311` deliberately refuses. Correction: unlisted/unenabled review actions stay Codex; an enabled pair in the wrong execution shape refuses. Preserve this boundary.
3. **“Writable receipts unchanged” conflicts with global matrix change**: `parse_request` reports all unconfirmed options and supported options supplied (`domain/invocation.py:77–86`). Changing read_only to supported changes False receipts too. Correction: writable argv/tools/session/outcomes unchanged; explicitly accept the two metadata assertion updates listed above, plus policy/config digests. No other historical receipt rewriting.
4. **Selected Docker path still refuses**: `executor.py:391–399` sends any Claude assignment to configured isolation; `adapters/isolated_worker.py:716–720` rejects every read_only run. Trigger: enable a design pair on an isolation-enabled host. Consequence: no design execution despite this transport feature. Minimal bounded correction to SPEC: this item delivers the host Claude transport/policy capability; selected isolated read-only remains unsupported/fail-closed pending a separate scoped item. Never bypass configured isolation to force success. If the owner requires live isolated design execution in this item, that is an explicit scope amendment before implementation, not an undocumented extra edit.
5. **Council host enablement is overwritten in the operation runner**: `adapters/autonomous_cli.py:12–15,44` reuses `operation_cli.execution_policy`; `adapters/operation_cli.py:88` overlays `domain/operation.py:183`’s worker-only ZEUS_CLAUDE_ASSIGNMENTS over host settings. Thus packaged permission ≠ runnable enabled council through that entry. Correction: describe this slice as permitted routing/transport, not completed operational council rollout; owner must include the overlay-preservation fix in the enablement slice (or explicitly amend this one). No broad operation manifest redesign is needed here.
6. **Accounting labels also remain old on future enablement**: Front Desk `adapters/frontdesk_cli.py:60–63` labels all calls Codex/Astra; council `application/autonomous.py:82–85,181–182,264` labels all non-worker calls Codex/model_routing. Trigger: a new Claude design call actually runs. Consequence: ledger label differs from actual provider although call counting remains. Correct SPEC’s “ready for enablement” claim: bind those labels to selected provider before live rollout; keep this as a named enablement prerequisite if not added to this slice. Do not fabricate model-served evidence.
7. **Postchecks are not universal proof**: council/frontdesk do check checkout; plan branch1192–1203 does not add a before/after Git check. Preserve existing checks as requested, but do not claim all design paths have them or that stream observation prevents every possible side effect. A non-read-only tool request is detected after emission; prevention rests on restricted tool exposure/permissions. Real-call verification remains separately owned, not inferred from fake-process tests.

Confirmed, not defects: conductor/dge_role is the existing council arbitration path (not review_conductor); lead:improvement is the actual plan recipient; v2 packet author uses lead:researcher; other readonly review/diagnosis/source-analysis callers stay Codex because they have no added pair. No new teams or review route are required.

## 5. Minimal operation allowed_paths and focused commands

For the bounded host-transport/policy slice with the above explicit operational exclusions, use exact files:

```json
[
  "src/codex_harness/resources/providers.json",
  "src/codex_harness/domain/providers.py",
  "src/codex_harness/domain/invocation.py",
  "src/codex_harness/adapters/claude_cli.py",
  "src/codex_harness/adapters/executor.py",
  "tests/test_claude_assignment.py",
  "tests/test_claude_cli_process.py",
  "tests/claude_protocol_child.py",
  "tests/test_claude_execution.py",
  "tests/test_model_routing.py",
  "docs/contracts.md",
  "docs/model-routing.md"
]
```

Owner clarifies the goal SPEC before pinning the manifest; the Fleet worker does not expand allowed_paths to silently implement isolation/ledger/config follow-ups. Existing classification and persistence need no new outcome module or vocabulary edit beyond support metadata. No organization.json/profile document edits.

Worker commands (proposed, **not run by Codex**), using its supplied context interpreter:

```sh
python -m pytest -q tests/test_claude_assignment.py tests/test_claude_cli_process.py tests/test_claude_execution.py tests/test_model_routing.py
python -m pytest -q tests/test_claude_review_boundaries.py tests/test_invocation_ledger.py tests/test_subscription_accounting.py tests/test_operation_cli.py tests/test_worker_profile.py tests/test_autonomous_roles.py tests/test_council_roles.py tests/test_frontdesk.py
python -m ruff check .
```

These exercise affected behavior and unchanged adjacent contracts; author/CI owns repository-required full verification. Do not run real model canaries from unit fixtures or silently spend the experiment budget. No provider/model replacement. Deliver code/test evidence separately for independent confirmation; this document approves nothing.
