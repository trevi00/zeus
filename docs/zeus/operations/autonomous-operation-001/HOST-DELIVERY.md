# Durable host delivery of a reviewed release

2026-09-23. Frame: `SPEC.md`, "Durable delivery controller: consolidated Batch 3 implementation".
Contract: `docs/contracts.md`, INV-HOST-DELIVERY-001. Implementation:
`src/codex_harness/domain/host_delivery.py`, `src/codex_harness/application/host_delivery.py`,
`src/codex_harness/adapters/host_delivery.py`, with narrow reusable additions to
`src/codex_harness/application/release_queue.py`, `src/codex_harness/adapters/monitoring.py`,
`src/codex_harness/domain/observation.py` and `src/codex_harness/cli.py`.

**Purpose.** Replace the one-shot PR181 continuation with a reusable, owner-controlled component
that carries an already reviewed candidate from its repository to an actual host runtime and
proves — or refuses — every step of it.
**Owner.** Implementation Claude; independent acceptance Codex; registration, the opt-in setting,
the qualified live canary and the real host gate stay with the repository owner.
**When to read.** Before registering a target or a plan, before enabling delivery on a host, and
before citing a `status` projection as evidence of anything.

This is a delivery controller. It is **not** an approval authority, **not** an evaluator, **not** a
scheduler, **not** a merge policy and **not** a claim that a host is qualified. The existing owners
keep every authority they had:

| existing owner | what it still decides | what this component does with it |
|---|---|---|
| `application.releases.Releases` | lead + conductor approval, the incumbent checks, the active-release CAS | reads the record, re-derives the approval, calls `promote` only after the prescribed checks **and** an actual consumption receipt |
| `application.release_queue.ReleaseQueue` | one controller per host, generation/lease/fence, attempts and backoff | claims under it, re-checks ownership inside every committing transaction, returns the lease for external waits |
| `adapters.git.GitWorkspace` | target repository, tree and patch re-derivation, `--match-head-commit` merge | publishes and merges through it; nothing re-implements those checks |
| the registered scheduled task / owned child process | what actually runs on the host | starts and ends exactly the service the owner registered |

The legacy Docker `ReleaseRunner` is untouched: it is not enabled, driven or replaced here. Do not
run the legacy supervisor on a host that uses this controller — both claim the same
`deployment_locks:controller` lease, which serializes them, but the legacy loop does not filter the
queue rows it claims and would run its own Docker pipeline on a delivery row.

## What the owner registers

Two separate documents, deliberately:

1. **The host target registry** (`urn:zeus:host-delivery-targets:1`), host configuration:
   `target_id`, `kind` (`windows_scheduled_task` or `process`), `root`, `state_dir`, `service`.
   `zeus host-delivery register-targets --file targets.json`.
2. **The delivery plan** (`urn:zeus:host-delivery:1`), read from Git at an explicit commit:
   `zeus host-delivery register --revision <40-hex> --path docs/.../delivery.json`.

```json
{"schema": "urn:zeus:host-delivery:1", "plan_id": "delivery-plan-1", "release_id": "<release id>",
 "revision": "<40-hex candidate revision>", "tree": "<64-hex candidate tree>",
 "policy_hash": "<64-hex incumbent evaluator hash>", "repository": "github:owner/repo",
 "required_checks": ["ci / required"], "target_id": "collect-service",
 "expected_descriptor": null, "canary_check_id": "collect_monitor_source",
 "target_descriptor": {"revision": "<40-hex host revision>", "worker_image": "unchanged",
                       "profile_digest": "unchanged"},
 "ci_timeout_seconds": 1800, "consumption_timeout_seconds": 120}
```

A plan may only **name** a registered target id. It carries no command, argv, path, host root,
service name or credential, and nothing in it is executed or interpolated anywhere. `unchanged` is
the explicit statement that this delivery does not move the image or the profile; it resolves
against the descriptor the target is actually running, and a target with no current descriptor
refuses it rather than guessing. `expected_descriptor` is the digest of the descriptor the owner
approved switching **from**; `null` means this target has none yet.

## The stage path, and what each stage proves

```
registered -> awaiting_review -> publishing -> awaiting_ci -> merge_intended -> merged
           -> drain_intended -> switching -> awaiting_consumption -> active
```

`blocked`, `rolling_back`, `rolled_back` and `failed` preserve the stage they happened at, the fixed
reason code, the error TYPE and the evidence. One tick advances at most one stage.

| stage | what must be true to leave it |
|---|---|
| `awaiting_review` | the release record itself carries the author's own lead **and** a conductor accepting exactly this revision with evidence, and the candidate's revision, tree, evaluator hash and repository are exactly the plan's |
| `publishing` | a pull request exists for exactly the intended head — adopted if a previous tick already created it |
| `awaiting_ci` | every named check FINISHED SUCCESSFULLY for that head; absent, running, skipped, cancelled, neutral and failed are not a pass, and a moved head goes to requalification |
| `merge_intended` | the merge happened — recognized rather than repeated if a previous tick already merged |
| `merged` | the incumbent evaluator recorded `verified`, the target is registered, the current descriptor is the approved predecessor, and the whole target tuple plus the expected active release are written durably |
| `drain_intended` | new admission is paused and the target reports no active and no unconfirmed work |
| `switching` | the immutable descriptor was replaced atomically under the target lock against its expected predecessor, and the service was started exactly once |
| `awaiting_consumption` | the launched process's own startup receipt names this exact descriptor, revision, image and profile, and the named canary passed |
| `active` | `Releases.promote` moved the pointer under its own compare-and-swap |

## Idempotence, restart and the fence

The durable intent names the stage **before** the external action of that stage, so a lost response
can only reconcile what already happened. Recovery is observation, never a second attempt: the PR
for this exact head either exists or it does not; a merged PR is recognized; a running instance's own
receipt is recognized. A restarted controller reads the same durable intent and continues from it.

Every durable observation is committed in the same transaction that re-checks the claim's
generation, owner and lease (`ReleaseQueue.owned`), so a superseded controller cannot record what it
observed. A 20-minute CI run never sleeps under the lease: the tick answers `pending`, returns the
lease through `ReleaseQueue.defer` — which is explicitly **not** a failed attempt — and the stage's
own durable deadline ends the wait. Definite failures go through `finish` with the queue's unchanged
retry budget and backoff. No store transaction is open across GitHub, the filesystem, a subprocess or
another independently locking transaction.

## The host boundary

* The descriptor is **immutable**: replaced under a target-specific lock, only when what is there is
  exactly the expected predecessor, by one atomic `os.replace`. A held lock is a conflicting change
  on that target and is never broken.
* Active work is **drained, not killed**. The controller writes `pause.json` into the target's state
  directory and reads the service's own `work.json` (`{"active": n, "unconfirmed": n}`). A running
  service with no work report at all, or with an unconfirmed effect, blocks the switch. A real
  service an owner points at a target must therefore publish that report; the minimal shipped
  service publishes `{"active": 0, "unconfirmed": 0}`, which is a fixture's honest answer and not a
  claim about a real Fleet.
* A previous instance that cannot be proven gone is `previous_instance_unconfirmed`; no second one is
  started beside it.
* Activation is decided by the launched process's **own** startup receipt — instance id, pid, start
  time, the module root it actually imported, and the descriptor digest, revision, image and profile
  it actually loaded. A missing, malformed, foreign or previous-instance receipt never activates.
* Rollback restores the **exact predecessor tuple** and then proves it with that predecessor's own
  fresh receipt and a live process. A failed or unproven restoration is a blocked critical alert, not
  a `rolled_back` claim.

The service process is deliberately **not** owned through `ProcessTree`. That owner's Windows
boundary is a job object with `KILL_ON_JOB_CLOSE` (`adapters/background_service.py`), which ends the
tree when the handle closes — right for a launcher that outlives its child, wrong for a transient
controller that must leave a service running. The child is therefore started with the existing
`commands.no_console_kwargs` policy (hidden and in its own group on Windows, a new session on POSIX)
and identified afterwards by its recorded pid and its startup receipt. On the current Windows host
the real target is the registered scheduled task, whose own launcher already owns its tree.

Known limits, stated rather than engineered away: pid reuse is not resolved by the liveness check
(which is why activation is decided by the receipt's instance id, not by liveness); the `process`
kind is the POSIX and test target, while the Windows host target is the registered scheduled task;
and `schtasks /Run` starts the task the owner registered — this component never creates, deletes or
reconfigures one.

## The canary

Named by an incumbent fixed id only, never by text in a plan:

| id | what it actually checks |
|---|---|
| `startup_identity` | the owned process is still running and its receipt still names this descriptor |
| `collect_monitor_source` | the incumbent read-only monitor projection reports this descriptor as the consumed one for this target |
| `fleet_worker_operation` | the **owner's** own receipt for exactly this descriptor; this component starts no model, provider or worker |

Any not-passed verdict — including `canary_unavailable` and `canary_error` — sends the delivery to
rollback rather than to activation. A real qualified worker run remains owner acceptance work.

## Operating it

```
zeus host-delivery register-targets --file targets.json
zeus host-delivery register --revision <40-hex> --path docs/zeus/.../delivery.json
zeus host-delivery status
ZEUS_HOST_DELIVERY_ENABLED=1 zeus host-delivery tick        # one bounded stage
ZEUS_HOST_DELIVERY_ENABLED=1 zeus host-delivery run         # bounded loop; an empty queue idles
```

Delivery is **off** by default: without `ZEUS_HOST_DELIVERY_ENABLED` a tick registers, projects and
refuses every external action, and not even a durable intent is written. `run` idles without
provider calls and stops gracefully on SIGINT/SIGTERM, finishing the tick in flight.

`status` and the additive `host_delivery` monitor source project identities, the Git pin, descriptor
digests, the durable stage, fixed reason codes, counts and a bounded next action — never a descriptor
body, a host root, a service name, a PR title, a check log, an exception message or a credential.
Structured transitions are `general.delivery_stage_entered`,
`development.delivery_check_observed`, `operations.delivery_switched`,
`operations.delivery_rollback` and `operations.delivery_blocked`. A repeated idle poll re-enters no
stage and emits nothing.

**A collected status is a projection of durable records.** It is not evidence of a qualified live
host, a passed owner canary or a semantically accepted release, and `consumed: false` beside a
switched descriptor is exactly that: a switch that was not an activation.

## What was verified here, and what was not

Verified by the scoped suites (`tests/test_host_delivery.py`, `tests/test_host_delivery_cli.py`):
the plan and registry grammar; the release gate, including a registration that legitimately precedes
its review; the whole stage path against a real temporary descriptor file, a real detached child
process and that child's real startup receipt; CI pending, failed, missing and head-changed; lost
publish and merge responses reconciled exactly once; a restarted controller resuming one intent
without repeating its effects; a held lease and a stale claim; unconfirmed host effects blocking the
switch; a wrong receipt refusing activation; a failed canary restoring and proving the predecessor;
an unproven restoration blocking with a critical alert; disabled-by-default; the observation
vocabulary; and the absence of nested store transactions under `SerialStore`.

Not verified here, and deliberately owner work: any live GitHub publication, CI run or merge; any
scheduled-task mutation on the real Windows host; the qualified `fleet_worker_operation` canary; and
the isolated-PostgreSQL transaction-boundary test, which is integration-gated and skips without
`HARNESS_INTEGRATION=1`.
