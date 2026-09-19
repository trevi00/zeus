# Subscription accounting admission (batch008) — implementation report

State: implemented and focused-tested in the worker; NOT a live cycle, NOT an observed provider
reset, NOT a migrated dashboard. Owner full suite and CI are separate.

## What changed (allowed paths only)

- `src/codex_harness/domain/usage_policy.py` (new): the one policy. `validate_budget` keeps the
  legacy `{per_host, total}` shape byte-for-byte as canonical finite mode (an explicit
  `mode: finite` canonicalizes to it); `mode: subscription` is retained with the two numbers as
  migration metadata, not ceilings. Unknown modes and extra fields refuse. `headroom` (finite
  remainder, or subscription `remaining=null`, `ok` only for a readable ledger with no unreadable
  slot), `exhausted`, `accounting_mode`, `validate_grant` (nondecreasing numbers; a mode change
  with unchanged numbers is a valid grant; same mode and numbers is not).
- Domain validators (`operation`, `fleet`, `research_program`) use that policy; council/autonomous
  inherit it through the operation validator unchanged. Program template budget must still equal
  the program budget, so mode round-trips template ↔ program.
- `CallBudget.reserve(..., mode="finite")`: unknown mode refused; subscription still takes the
  machine lock, reads the ledger, refuses on unreadable slots, writes the slot (with
  `accounting_mode`) before any provider entry and settles as before. Lifetime counts never refuse
  subscription; finite behavior unchanged. No second ledger, no history reset.
- `BudgetedExecutor` binds the mode once from the ceilings, passes `mode=` ONLY for subscription
  (finite fakes see the legacy call), records `accounting_mode` per slot; `Operation.run`
  validates an override budget before the claim; the receipt carries `accounting_mode`.
- Fleet: `authorize_budget(..., mode=None)` (`--mode finite|subscription`; omitted keeps the current
  mode), idle-only, CAS on total, immutable grant record with `prior_mode`/`mode`; status and
  sanitized config carry `accounting_mode`; `LaneLauncher.budget_exhausted` uses the policy.
  Enqueue/admission mode mismatch stays `budget_mismatch` / `budget_stale`.
- Research program: `headroom` delegates to the policy (shape unchanged); status and monitor
  projections carry `accounting_mode`.

Not changed: deadlines, max_starts, max_cycles/adoptions, concurrency, ownership, failure stops,
credentials, provider selection, auth, runtime timeouts, provider-limit handling (explicit STOP on
provider error remains; no reset_at is ever invented). `docs/contracts.md` is outside the allowed
paths and still describes only the finite grant rules: follow-up for the owner.

## Verification (actual, this worker)

Commands and observed results are in the structured worker result. Notes:
- `tests/test_call_budget.py` named by the SPEC focused command does not exist in this checkout;
  the ledger tests live in `tests/test_claude_review_boundaries.py` (R4 block). The focused
  command was run as written and again without the missing file; see the result summary.
- Injected faults in the new tests are labelled: damaged slot file, fake unreadable ledger,
  edited control row standing in for a grant race. No provider, git CLI or network use.
- Full suite, PostgreSQL/Redis suites and CI: not run here (owner).

## Batch008 observed obstacle: provider-control correction (this worker, on the preserved code)

Observed (owner evidence, SPEC): the batch008 subscriber run stopped with
`result_subtype=error_max_budget_usd` at the legacy CLI estimate cap. Cause traced in code: the
accounting mode reached admission only. `provider_settings` forwarded `max_budget_usd` as an active
control regardless of mode, `select_execution` copied it into `assignment.controls`, the executor
put it into the invocation options and `ClaudeCodeRuntime` always passed `--max-budget-usd`. That
run is NOT observed subscription exhaustion and NOT an API bill.

What changed (allowed paths only; the accounting module is untouched):
- `domain/operation.py`: `provider_settings` always sets `ZEUS_CLAUDE_ACCOUNTING_MODE` to the
  manifest budget's mode (finite or subscription); the manifest keeps its positive numeric
  `max_budget_usd` and `validate_manifest` checks the controls with the mode bound in.
- `domain/providers.py`: the setting is read per transport (`ACCOUNTING_SETTINGS`, `claude_cli`
  only); unknown values refuse the configuration whole. Absent or `finite` produces the
  byte-identical legacy enabled entry and config digest. `subscription` still validates a present
  dollar cap by the same rules, does not require it, omits it from `controls`, writes
  `accounting_mode` into the entry (a different digest) and into the selected `runtime`;
  `ExecutionAssignment.accounting_mode` and its receipt name the mode. The default provider
  reports `finite`.
- `adapters/executor.py`: `invocation_options` builds the claude_cli request with `max_budget_usd`
  only when the assignment carries it (the old code sent a null, which the support matrix refuses).
  `_open_runtime` is unchanged: the mode rides in `assignment.runtime`.
- `adapters/claude_cli.py`: `runtime["accounting_mode"]` (absent = finite) is validated at
  construction; subscription refuses a configured ceiling, drops `--max-budget-usd` from the
  planned flags and the argv and records `max_budget_usd: null` plus `accounting_mode` in the
  command receipt; finite requires and passes the ceiling exactly as before.
- Isolated path: `isolated_worker.py` and `isolated_worker_entry.py` are unchanged. The request
  already serializes `runtime`; the entry hands it to `ClaudeCodeRuntime` unchanged. A test serves
  the entry in-process with the real runtime over the labelled protocol child; no container ran.

Not changed: deadlines, timeouts, schema, model, permissions, worktree/isolation, provider auth,
usage recording, the ledger, the fleet and program policy. No retry, no automatic grant. The old
immutable worker image still contains the old `ClaudeCodeRuntime`: the owner must rebuild and pin
the image from accepted source before any live subscription run; this change alone does not update
it. `docs/contracts.md` (INV-CLAUDE-WORKER-001, INV-OPERATION-001) now describes the mode.

Disposition notes for the owner: the setting name lives in `domain/providers.py` keyed by
transport because `resources/providers.json` was outside the allowed paths; a policy field would be
the tidier home. `ExecutionPolicy.summary()` (adapters/providers.py, outside allowed paths) still
lists only control names and does not print the mode.
