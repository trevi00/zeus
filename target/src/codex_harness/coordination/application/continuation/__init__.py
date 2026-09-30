"""Continuation (INV-CONTINUATION-001), split by responsibility (DESIGN-s6 §3): state, lanes, intents, frames,
research, successors, grants, requalification, settlement, tick and ownership. M7 module docstring:

Durable conductor continuation over the existing Fleet, lanes and owners (INV-CONTINUATION-001).

A thin coordinator, not a second executor, scheduler, reviewer or release authority. It owns four
buckets in the Fleet control store - `continuation_policies` (one registered Git-pinned owner
policy per id), `continuation_intents` (one durable intent per routed observation),
`continuation_progress` (one selection-progress row per policy: attempts only) and
`continuation_research_receipts` (one immutable owner receipt per research intent;
`continuation_capacity_grants` holds one owner capacity grant per budget-refused repair intent) - and one in
each lane store, `continuation_bindings` (the trusted document a lane Operation claim attaches to
its assignment). Everything else is reached through its existing owner:

* `Fleet.enqueue` admits a successor (same id on every replay; the Fleet's own lanes, paths,
  pause and ledger decide when it runs) and finite `zeus operate run` executes it unchanged.
* `WorkerSessions.record_review` moves the logical session on the committed independent review
  decision row; the executor resumes it natively only from `correction_ready`.
* The conductor port starts an owned child running the existing guarded
  `Executor.decide_one("conductor", expected=...)` for exactly the pending conductor row; the
  Releases/ReleaseQueue records it writes are read back.
* HostDelivery and the approved backlog stay the owners of delivery and of the next item; the
  controller records the handoff and observes their durable result.
* The existing Portfolio investigation and research dispatch are the research owners after two
  distinct similar failures; only the owner's scoped receipt (`accept_research`) for the exact
  intent and attempt set releases that hold.

One tick is a few short store transactions with every external effect strictly between them: no
transaction is open across a lane store, Git, a process or the Fleet's own transaction. Each effect
is preceded by a durable intent state and followed by its observed evidence, and each state change
is a compare-and-swap on the intent version, so two controllers and a restart converge on one
intent, one successor id and one dispatch. An idle tick writes nothing and calls nothing.

Restart is a table, not a guess: `domain.continuation.RESUME` names the one action for every open
(route, state) a crash can leave behind. The conductor is never waited on: the Fleet's shared
capacity authority reserves its execution unit in the SAME transaction that commits the launch
identity (`dispatched`), before `conductor.start` spawns the DB-free guardian that owns the conduct
tree; later ticks (or `drain`, when admission is closed) `conductor.poll` its local evidence. The
unit and the intent leave `dispatched` together, in one Fleet settlement, and only on an exact
proof: the guardian's confirmed parent-and-tree cleanup receipt or the never-entered fence. A
decision that succeeded while cleanup is unknown is neither completed nor retried; that debt keeps
its slot for its named owner.
Every NEW effect - lane binding, Fleet admission, conductor start - first passes `_authorize`, the
one eligibility guard comparing the current pinned policy, frame, model and runtime identity with
the authorization stored on the intent; reconciling an already started effect never needs it.
"""
