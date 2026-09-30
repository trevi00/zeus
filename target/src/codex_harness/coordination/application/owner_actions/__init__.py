"""Owner actions (INV-OWNER-ACTIONS-001), split into the scheduler, the action store and one object per family
(DESIGN-s6 §4). M7 module docstring:

The server-owned pending-action coordinator (INV-OWNER-ACTIONS-001, aibox-migration-001 SPEC s14).

One thin durable owner for the three handoffs no unattended owner performed before: the independent
scoped acceptance of a held research family (G1), the exact approved delivery-plan publication for a
conducted release (G2) and the owner's actual canary of that delivery (G2). It is not a scheduler, a
reviewer, a release authority or a deployment controller. Everything decisive stays with its owner:

* `Continuation.accept_research` (validated, immutable, idempotent receipt storage) and the Fleet
  continuation tick that later releases the hold; this coordinator only assembles the receipt from the
  same authoritative reads (`Continuation.research_facts`) and one independent assessment.
* the existing guarded `decide_one` of the independent assessor, with its lease, attempt budget,
  execution budget and evidence receipt: one `owner_assessment` decision row per action, executed in a
  DB-free guardian the `assessments` port spawns once per launch identity. An existing executed
  assessment bound to exactly the same binding digest is reused instead of a new call.
* `Releases`/`HostDelivery` (`approval`, `register`, stages, merge, canary gate, rollback) and the
  incumbent `fleet_worker_operation` canary check, which reads the receipt this coordinator writes
  only from an ACTUAL finished canary operation and its independent lead review.

Durability follows the continuation rule: each action is one row in `owner_actions` (Fleet control
store) keyed by the digest of its kind and exact binding; the row names the state BEFORE the effect of
that state (`intended`, `assessing`, `invoking`, `publishing`, `published`, `requested`) and each move is
a compare-and-swap on its version, so a restart or a second coordinator reconciles instead of repeating.
No transaction is open across a lane store, Git, a process, an artifact write or the continuation's
own transactions. Rejected, unknown and refused are named terminal states: nothing here retries a model
call on a timer, and changed evidence is a NEW action while the old one keeps its history. An idle tick
writes nothing and calls nothing.

Policy v2 adds two opt-in handoffs, each to its existing owner (aibox whole-goal adjudication C1/C3):

* `delivery_requalify` - a completed plan of this policy whose delivery the controller BLOCKED as
  `reviewed_base_moved` is withdrawn through the lane's GitHub-capable `HostDelivery.withdraw` (the host was
  never touched; staleness observed now) and then requalified through `Continuation.requalify_delivery` on
  the observed current main with a persisted owner document (never a goal migration). A per-family cap
  slot is taken atomically with the move out of `intended`; the cap counts slots already held, never the
  action itself. Unobservable GitHub or main keeps the row where it is: the debt stays owned.
* `research_dispatch` - a held family the ported RO-1 rule scopes exactly gets ONE guarded
  `research-program run <program> --ticks 1` child: the provider probe runs before any resume,
  reservation or spawn, the launch id (which is also the cycle owner token) is persisted before the
  spawn, later ticks only poll, and the child's own cycle rows decide the outcome. A launch that provably
  never entered is relaunched at most once; unknown cleanup or a foreign cycle is `unknown`, never relaunched.
"""
