# fleet-autonomy-001 — responsibility routing: design-heavy read-only roles on a proven read-only Claude execution

Status: owner specification (Claude, main owner). Codex refines the detail and independently confirms the delivered
change. This is the goal document of the first backlog item of plan `fleet-autonomy-001`.

## 1. Decision and completion condition
The user's role policy (2026-09-28 KST) assigns each Zeus role by its concrete task responsibility:
- design-heavy leads and workers → Claude;
- detail-heavy leads and workers → Codex;
- Claude executes and delivers; Codex confirms results.

The original teams, council versions and SDD labels stay unchanged, and every existing independent review stays with
Codex.

Today `resources/providers.json` selects Codex for everything except the writable `worker:implementation/implement`
pair. The Claude transport refuses every read-only run (`adapters/claude_cli.py`: "claude_cli cannot prove a read-only
execution"; `domain/invocation.py`: claude `read_only: unconfirmed`). Every design-heavy role in the inner workflow is
read-only, so none of them can be routed to Claude.

**Criterion:** "Design-heavy read-only Zeus roles can be routed to Claude only through a proven read-only Claude
execution, while every independent review, verification and state-correctness role stays on Codex."

Done when all three hold:
- (a) a read-only Claude execution runs only under a validated restricted profile and refuses any observed
  non-read-only tool use;
- (b) the packaged policy permits exactly the listed design-heavy read-only (role, action) pairs;
- (c) enablement stays host configuration, and nothing routes to Claude until a host enables a permitted pair.

## 2. Scope (this item only)
### 2.1 Proven read-only Claude execution
- **`providers.json`**: the `claude` provider gains a `read_only_runtime` object that overlays `runtime` for read-only
  executions only:
  - `tools`: `["Read", "Glob", "Grep"]`;
  - `allowed_tools`: `["Read", "Glob", "Grep"]`;
  - `disallowed_tools`: at least `["Bash", "Edit", "Write", "NotebookEdit", "Task", "WebFetch", "WebSearch",
    "mcp__*"]`;
  - `permission_mode`: exactly `"dontAsk"` (CLI 2.1.280 modes: acceptEdits, auto, bypassPermissions, manual,
    dontAsk, plan), together with the existing `permission_prompts: "none"`;
  - `restricted`: exactly `true`, so the CLI `--restricted` flag confines file tools to the working directories and
    ignores user/project/local settings. The base runtime stays `restricted: false`.
- **`domain/providers.py`** validates `read_only_runtime` when present, and refuses the whole policy otherwise:
  - only those keys;
  - `tools` and `allowed_tools` are non-empty subsets of the read-only tool set {Read, Glob, Grep};
  - `disallowed_tools` contains every mutating tool name (Bash, Edit, Write, NotebookEdit);
  - `permission_mode` is exactly `dontAsk`;
  - `restricted` is exactly `true`;
  - no wildcard or pattern names (for example `Read(*)`) are allowed.

  A present but null, empty or malformed overlay never counts as absent. A read-only claude assignment rule without a
  valid overlay refuses the policy. One shared domain validation helper serves both the policy parse and the transport
  preflight.

  `select_execution` applies the overlay only when `read_only` is true and the selected provider declares it. The
  assignment receipt records that the read-only profile was applied.
- **`adapters/claude_cli.py`**:
  - `run(read_only=True)` validates the EFFECTIVE runtime and the final per-run settings with the shared predicate
    before any process starts; it never trusts a marker.
  - It refuses a read-only run that carries a worker profile, project delivery, task session or added settings. Those
    may add Bash grants or hooks, and no read-only variant of the implementation profile is invented here.
  - During a read-only run, every normalized `tool_started` event is checked in the event loop, before any retention
    limit. A tool name outside the profile's allowed names, including a missing name or a missing id, latches a
    violation. The run stops through the existing termination and cleanup path.
  - The result is the existing `provider_failure` outcome with the fixed diagnostic reason `read_only_violation` and
    answer None. The violation takes precedence over a success terminal seen before or after it, and over the
    missing-terminal fault caused by the stop.
  - Unknown-cleanup and stream-loss facts are kept. No tool payload is echoed into diagnostics.
  - Writable runs keep their argv, tools, sessions and outcomes.
- **`domain/invocation.py`**: claude_cli `read_only` becomes `supported`, because the effect is checked here (the
  restricted argv plus the observed tool uses). The four-state vocabulary and the OUTCOMES are unchanged.

  Accepted metadata delta: request receipts, writable ones included, now list `read_only` among the options whose
  effect is verified here (`tests/test_claude_cli_process.py` and `tests/test_claude_execution.py` expectations).
  Nothing else in historical receipts changes.
- **Callers keep their existing post-checks**: the clean checkout and unchanged HEAD for council roles, the Front Desk
  and reviews.

### 2.2 Packaged design-heavy read-only assignments (policy only; not enabled)
Assignments are added to `providers.json` with provider `claude`, `read_only: true` and workload `design`:

| Roles | Action | Responsibility |
|---|---|---|
| `lead:research`, `lead:improvement` | `dge_role` | council v2 research-lead proposal and improvement-lead constructive alternative |
| `conductor` | `dge_role` | council v2 design arbitration |
| `lead:researcher`, `lead:proposer`, `lead:arbiter` | `dge_role` | v1 packet synthesis, proposal, design arbitration |
| `lead:frontdesk` | `frontdesk` | request framing |
| `lead:improvement` | `plan` | the improvement plan. `adapters/executor.py` passes `action="plan"` for plan tasks, which today pass none |

Selection semantics are unchanged:
- a pair that is unlisted, or listed but not enabled on the host, selects Codex;
- a host-enabled pair used with the wrong workload or read_only flag REFUSES, with no silent fallback.

These stay Codex, with no assignment:
- `lead:dba` and `lead:attacker` (`dge_role`), which do state-correctness and concrete refutation;
- every review/decision phase (`review_*`, conductor review, final validation, diagnosis);
- the research workers.

The writable `worker:implementation/implement` rule is unchanged.

### 2.3 Documentation
- `docs/contracts.md` INV-CLAUDE-WORKER-001 gains a "responsibility routing" addendum:
  - the pairs;
  - the read-only proof;
  - what stays Codex;
  - that enablement is host configuration.
- `docs/model-routing.md` gains a short section with the same table.

## 3. Out of scope

This item delivers the permitted policy and the proven HOST-transport read-only capability. It does NOT deliver a live
council or Front Desk rollout on aibox. The prerequisites of such a rollout are named follow-up items:
- **Isolated (Docker) execution:** `adapters/isolated_worker.py` still refuses every read-only run. The executor sends
  every Claude assignment to the configured isolation, so read-only isolated execution needs its own scoped item.
  Isolation is never bypassed.
- **Enablement for the council:** `adapters/autonomous_cli.py` reuses `operation_cli.execution_policy`, whose manifest
  overlay replaces the host `ZEUS_CLAUDE_ASSIGNMENTS`. Enabling council pairs needs overlay preservation.
- **Ledger labels:** the Front Desk and council accounting labels name Codex/Astra for every call. They must name the
  selected provider before any live Claude design call.
- **The plan branch** has no before/after checkout check (the council and the Front Desk have one).

Also out of scope:
- Host enablement (`ZEUS_CLAUDE_ASSIGNMENTS`), credentials, and any service or unit change: these are owner operations
  after delivery.
- A real-call confirmation of the read-only profile: an owner operation within the experiment call budget.
- A Codex worker choice for detail-heavy operations: a separate follow-up item.
- Changing `default_provider`.
- Routing any review to Claude.
- Frontend/visual work.

## 4. Acceptance
1. A read-only Claude run starts only with the validated profile. A profile that grants any mutating tool is refused
   before spawn. A read-only run whose stream shows a tool outside Read/Glob/Grep is refused as `read_only_violation`
   and never yields an accepted result. Fake-process tests cover both, plus a clean read-only run.
2. The packaged policy permits exactly the listed (role, action) pairs as read-only design workloads. With a host
   enabling them, the listed pairs select Claude. `lead:dba`/`lead:attacker` `dge_role`, the reviews,
   `final_validation`, diagnosis and every unlisted pair select Codex. Enabling an unlisted pair is refused as
   before. A table-driven test covers each row.
3. Plan tasks pass `action="plan"`. The writable implementation path, its receipts and every existing test keep their
   behaviour. Tests that pin the packaged policy bytes or digest are updated only for the changed bytes.
4. `python -m pytest -q tests/test_claude_assignment.py tests/test_claude_cli_process.py tests/test_claude_execution.py
   tests/test_model_routing.py`, the adjacent-contract modules (`tests/test_claude_review_boundaries.py`
   `tests/test_invocation_ledger.py` `tests/test_subscription_accounting.py` `tests/test_operation_cli.py`
   `tests/test_worker_profile.py` `tests/test_autonomous_roles.py` `tests/test_council_roles.py`
   `tests/test_frontdesk.py`) and `python -m ruff check .` pass. The fake-process scenarios reuse
   `tests/claude_protocol_child.py` and keep its default behaviour; they are fixture evidence, not a real-call proof.

Detailed edit sites, test names and boundaries: `DETAIL.md` in this directory, which is Codex's refinement of
2026-09-27T15:52Z, adopted by the owner with the scope in §3. Where DETAIL.md offers a choice, this SPEC decides:
- the `restricted: true` overlay key;
- `dontAsk`;
- isolation, enablement and labels are out of scope.
