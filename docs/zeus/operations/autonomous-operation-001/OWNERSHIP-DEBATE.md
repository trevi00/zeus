# Research packet: continuation process ownership

Date: 2026-09-23. Parent frame: SPEC.md. This is a bounded research/debate record for the
second rejected implementation, not another completion contract or evidence of a live Council run.
Pinned subject: 1bd95a36b5c0b167912f176f583673de2b31aa27. Two distinct rejected candidates
77dbb04f and 1bd95a36 exposed the same lifecycle family; this triggers the existing two-strike rule.
No new implementation is authorized from this packet until the debate disposition is recorded.

## Questions that change the decision

1. Which existing authority reserves shared capacity before BOTH worker and conductor launch?
2. Who continues deadline enforcement if PostgreSQL reads fail or block?
3. What observed evidence permits releasing a process handle, its capacity and its logical intent?

## Sources and limits

S1. Python 3.14.7 subprocess documentation, opened 2026-09-23:
https://docs.python.org/3/library/subprocess.html#subprocess.Popen.communicate
Popen communication timeout alone does not end the child; explicit cleanup and completion are
required. This supports separating timeout detection from cleanup confirmation. It does not
establish whole-tree death or the behavior of Zeus's ProcessTree implementation.

S2. Microsoft Win32 Job Objects, opened 2026-09-23 (page has no pinned API version):
https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
Jobs group associated processes; some completion-port notifications are not guaranteed. An absent
notification is not proof that an event did not occur. OS ownership/query evidence is required;
neither a wrapper exit nor a discarded handle proves complete cleanup. Windows facts do not prove
POSIX process-group behavior or arbitrary escaped descendants.

S3. PostgreSQL 18 explicit locking/advisory locks, opened 2026-09-23:
https://www.postgresql.org/docs/18/explicit-locking.html#ADVISORY-LOCKS
Advisory lock meaning is application-defined and every participating path must use it consistently.
It supports central transactional admission, not the claim that a DB lock owns or kills OS children.
Database unavailability must stop new admission but cannot be the local cleanup dependency.

S4. Pinned implementation source traces (not yet executed fault reproductions):
- FleetRunner.run invokes continuation before _admit; _admit counts workers+conductors locally,
  while continuation launch checks the conductor port's own capacity. Thus a full worker pool
  does not gate that earlier conductor launch.
- Continuation.drain reads the store before polling children. ConductorProcesses.poll is the
  sole enforcement of its deadlines. Store failure can therefore bypass timeout cleanup.
- ConductorProcesses._release pops its child before termination and closes the handle even when
  confirmation is false; settlement does not require cleanup_confirmed. Decision success and
  process cleanup are different facts, currently conflated.
- Existing Fleet.admit_one reserves worker work transactionally; unknown jobs retain capacity.
  Existing ProcessTree.terminate returns a combined parent/tree confirmation. Reuse these owners.

## Competing designs for debate

A. Patch local counts and reorder polling. Small change, but local counts alone cannot reserve
across multiple controllers/restart, and polling before one DB call cannot supervise during a
blocked subsequent DB call. Must prove the whole ownership contract or reject this option.

B. Extend existing Fleet admission as the shared durable capacity authority, and separate
DB-independent local child supervision from durable workflow settlement. Keep the existing
ProcessTree/hidden process conventions. Reserve -> start -> running -> cleanup pending/unknown ->
cleanup confirmed -> settlement pending -> released. Retain uncertainty as owned debt, never as
spare capacity. Slot expiry alone is not permission to launch a replacement. This is the preferred
design hypothesis, subject to debate of restart, fencing and who owns the local supervisor.

C. Replace Fleet/continuation with a new scheduler or event engine. No evidence requires this
scope; compare only to explain why existing owners can or cannot be extended.

The application result and process lifecycle are separate axes. A succeeded decision may remain
awaiting cleanup. Conversely a cleaned child with an unavailable DB keeps its completion receipt
and capacity reservation until durable settlement. Do not lose authoritative evidence for neat UI.

## Fixed debate/acceptance matrix

- Full shared capacity: conductor first, worker first, simultaneous controllers; zero excess start.
- Reserved-before-spawn restart and lost launch response: no duplicate and no unsafe TTL release.
- Real sleeping owned child + database outage/block: deadline cleanup proceeds without store access.
- terminate exception/false, parent exited but tree unknown: handle/evidence/debt retained; no reuse.
- Successful decision + unknown cleanup: no logical completion/replacement; reconcile without rerun.
- Confirmed cleanup + failed DB settlement: durable local receipt; after recovery settle exactly once.
- Graceful stop and owner restart preserve debt; unknown ownership never kills a foreign PID.
- Healthy unrelated work advances while free capacity exists. If unresolved debt consumes ALL slots,
  admission stops honestly; fairness cannot override the configured physical safety limit.
- Windows Job Object and POSIX group checks reported separately; labelled faults are not real outages.

Debate roles: proposer must select reuse/extend/build with concrete state/owner table; attacker may
raise only reachable material acceptance failures with evidence; root Codex arbitrates unresolved
tradeoffs and writes one consolidated Claude handoff. No speculative issue expansion.

## Actual debate record and arbitration

Executed as Codex research/proposer/attacker subagent sessions with root Codex arbitration, on
2026-09-23. This was NOT the Zeus Council/Redis production pipeline; do not promote it as evidence
that the unfinished autonomous research path works. Roles: ownership_ssot (source researcher),
ownership_proposer, ownership_attacker; the latter two exchanged the concrete proposal and critical
counterexamples. Claude receives only the resulting implementation specification.

Research correction: LaneLauncher uses Popen, not ProcessTree. Existing ProcessTree.terminate
requires parent AND boundary confirmation. background_service closes after a failed cleanup but
reports that uncertainty with precedence; that close cannot be reused as proof of reclamation.

Owner executed two synthetic faults against pinned 1bd95a36 (no real child or production DB):
termination confirmed=False left children empty and closed the handle; injected store outage
resulted in zero local polls. Receipt: artifacts/autonomous-operation-001/
ownership-debate-discriminator.json. Capacity overrun remains a source-traced finding, not an
executed concurrency reproduction. None of these checks proves the proposed correction.

Proposer chose B: existing Fleet shared transactional admission plus an independent per-launch
guardian, adapting continuation_process.main to own the actual conduct ProcessTree. Guardian
supervision must never query PostgreSQL. It survives Fleet blockage/exit, retaining the child until
confirmed cleanup has an identity-bound durable local receipt. Fleet owns durable settlement.
Rejected A: local counts/poll reordering cannot satisfy multi-controller or blocked-DB boundaries.
Rejected C: no evidence requires another scheduler or replacing existing review/release owners.

Attacker required: all entry points use shared reservation; stale delayed launch cannot execute;
lost response cannot duplicate spawn; guardian survives controller loss; parent-only exit cannot
release capacity; local receipt write failure preserves debt; DB commit failure settles once.
After proposal exchange, attacker found no remaining material design blocker, CONDITIONAL on the
fixed tests below. This is design acceptance, not implementation acceptance.

Root arbitration: max_parallel bounds execution units (worker job or conduct decision), not every
OS PID within their process trees. A single delayed, fenced guardian may start as bookkeeping but
must execute zero conduct commands; unbounded wrapper retry is forbidden. Unknown debt consumes
capacity; if all slots are held, admission stops honestly. Forced guardian death is unresolved
ownership, especially on POSIX; do not claim process-tree reacquisition from PID or automatic
recovery without proof. A standalone tick must use the same reservation authority. Retain normal
finite-operation behavior and previously accepted restart/target/authorization boundaries.

The consolidated implementation/state table and acceptance matrix are in the parent SPEC section
"Two-strike ownership design after research and debate". No patch may substitute local counters,
DB-first cleanup, TTL-based release or a success decision for its ownership requirements.
