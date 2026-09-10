## FA-017 closure — final bounded review (source slice only)

**Verdict: no concrete blockers remain in the bounded identity/queue/time-contract slice.** All four gaps from my prior review are closed; production code is unchanged and still reads correctly.

**Gap 2 — owner conflation: closed.** `test_execution_identity.py:49-52` now selects the message per field (`Stale or expired task execution` for `lease_owner`, `Stale failure retry` otherwise) with the comment at `:50` recording *why* the altered owner misses the digest and lands on the ordinary ownership/status path. The two mechanisms are now separately pinned, matching discussion.md:34-35.

**Gap 3 — decision shape: closed.** The `decisions_pending` row is now produced by the real path (`complete` → outbox report → `w.handle`), and `:36` asserts the true shape (`actor` present, `agent` absent) rather than a copied tasks lease. `:53-56` then supplies a caller dict with `actor` stripped against a stored row that has one, so `_same_execution` (`workflow.py:181-188`) does real work on an asymmetric row. Decision-state poison containment is covered by `test_bad_decision_status_is_contained_before_claim` (`:98-112`), which fills the previously untested `InvalidExecutionState` branch.

**Correction to my earlier wording.** I framed the missing-key case as one over-rejection risk; that was imprecise, and the asymmetry is deliberate, not a defect. A lease missing `actor` against a real actor-bearing decision row *must* reject (`current.get('actor')` vs `None`), and that is what `:53-56` asserts. A lease missing `actor` on an ordinary tasks row *must* pass, since `default = None` applies to both sides — asserted by the idempotent replay at `:48` under the `tasks` parametrization. Both directions are now covered; nothing here needs a further test.

**Gap 4: closed.** `test_failure_receipt_retains_historical_digest` (`:62-71`) pins a literal hex receipt against a fixed `message_id`, so canonicalization drift now fails loudly. Pre-recovery receipt replay is already fenced in `test_execution_recovery.py:64-65` (`fail(lease)` post-`apply` raises `Stale`) across both backends; I am not asking for a duplicate.

**Gap 1** was the documentation of mandatory `created_at`, not a code defect; discussion.md:15-19 now states the blocking behaviour, the refusal to invent times, and the operator repair obligation.

Remaining items are non-source: exact-revision regression run, criterion observations, and external human approval — closure evidence stays a draft until those exist.