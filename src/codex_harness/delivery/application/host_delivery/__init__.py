"""HostDelivery (INV-HOST-DELIVERY-001), split by responsibility (DESIGN-s7 V8): state, controller,
registry, the stage handlers (stages/*), withdrawal, resumption, recovery and migration. There is no
facade: composition (S10) wires the objects. M7 module docstring:

Durable delivery of a reviewed release to an actual host target (INV-HOST-DELIVERY-001).

A bounded coordinator, not a second approval authority and not a second executor. It owns four
buckets over the existing store - `host_delivery_targets` (the owner's authorized host registry),
`host_delivery_plans` (one registered Git-pinned plan per plan id), `host_delivery_intents` (one
durable intent per plan) and `host_delivery_descriptors` (the active descriptor of each target) -
and it reaches everything else through its existing owners:

* `application.releases.Releases` remains the only approval and the only active-release CAS. The
  lead+conductor reviews, the exact revision/tree/evaluator hash and the ticket binding are read
  from ITS record; nothing here writes a review, and `promote` is called only after the prescribed
  checks AND an actual consumption receipt.
* `application.release_queue.ReleaseQueue` remains the fence: one controller on this host at a
  time, with its generation, lease, attempt budget and backoff unchanged. This controller claims
  only the rows a registered plan names.
* The GitHub port publishes and merges through the existing `GitWorkspace` contracts and observes
  the real checks of the exact PR head; the host port owns the descriptor, the drain and the
  process; the canary port is an incumbent fixed check id, never text from a plan.

One tick is a few short store transactions with every external action strictly between them,
because `PostgresStore.transaction` takes `pg_advisory_xact_lock` per transaction and a nested call
would block until `lock_timeout`. No transaction is open across GitHub, the filesystem, a
subprocess or another independently locking transaction, and every durable observation is committed
in the same transaction that re-checks this controller's ownership.

Idempotence follows the durable-intent rule: the intent names the stage BEFORE the external action
of that stage, so a lost response can only reconcile what already happened - an existing PR at the
intended head is adopted, an already merged PR is recognized, and an already consumed descriptor is
recognized - never repeated. A long external wait (CI, startup) does not sleep holding the lease:
the tick answers `pending`, releases the lease through `ReleaseQueue.defer`, and the next bounded
tick resumes the same logical intent under its own durable stage deadline.
"""
