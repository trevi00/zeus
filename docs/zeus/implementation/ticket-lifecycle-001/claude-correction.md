Verified both corrections by tracing each of the four tests against the code.

## The fix is correct

**Reconcile scoping** (`:108`, `:145-146`): `reconciled` is hoisted before the `if issue:` block so it's defined on the `issue is None` path, and the pending transaction retains the prior `observed_*_hash` whenever `reconciled` is true. `pending_body_hash` is always `digest(body)` of a local projection, so it was never a leak vector. Confirmed on both parametrizations of `test_failed_reconcile_does_not_authorize_plain_retry_after_revision_change`: after the failed edit, the accepted set is `{digest(body), pending=digest(body), observed=projection, link.body_hash=projection}` — the foreign content is absent, so the plain retry raises both before and after the local revision bump, and only the explicit `expected_revision=2` + observation retry proceeds. That last step is the right semantics: the observation binds the exact remote bytes, and the operator re-authorizes against the current revision.

**The CLOSED-conflict leak you found is the same bug one layer down, and the fix closes it properly.** `:185-186` advance `link.body_hash`/`title_hash` only on `projection_matches`, `:206-207` do the same for the claim's accepted hashes, and the external measurement lands in the separate `observed_body_hash`/`observed_title_hash` fields on the record. Critically, the acceptance checks at `:122-123` and `:128-130` read only `link["body_hash"]` / `link.get("title_hash")` and never the record's `observed_*`, so the measurement is inert. Both conflict tests genuinely distinguish this:

- `test_closed_issue_reconciliation_does_not_trust_unwritten_foreign_content` — reconcile on CLOSED skips the write, so the foreign body was never ours; after the external reopen the plain sync correctly raises. Under the old code the link would have absorbed `digest("External content")` and the reopened sync would have silently overwritten.
- `test_closed_issue_readback_does_not_promote_new_external_content_to_trusted` — the `reads == 2` hook mutates the body between the conflict read and the post-write read, exercising exactly the window where the second `_read` result would otherwise have been promoted. The pre-write `state_conflict` value correctly suppresses the readback `require` at `:175`, and the changed body reaches the record only as `observed_body_hash`.

No KeyError exposure from the new `None` values: a link that never projected successfully carries `body_hash: None`, and `:123` compares rather than indexes into it; `title_hash` is already accessed via `.get`. Legacy records always carried `body_hash`, so `:123`'s direct subscript stays safe.

## No blockers

Two legibility nits, neither affecting behavior and neither worth holding the patch for:

- `record["title"]` (`:188`) holds the *external* title while `record["title_hash"]` holds the *trusted* one, so in a `state_conflict` record `digest(record["title"]) != record["title_hash"]`. Nothing computes on it, but renaming to `observed_title` would match `observed_body_hash` / `observed_state` and remove the trap.
- `reconcile_observation` is still persisted at `:147` and never read; clearing it to `None` at finalization would stop a future reader from mistaking it for a standing grant.

## Approval

Approved. The reconcile leak and the CLOSED-conflict variant are both fixed, the tests fail against the pre-fix code and pass against the fix, and foreign content can no longer become authority through either the claim or the link.

Scope unchanged: this delivers FA-029 acceptance criterion 5 and the criterion-4 ACK/ownership/lease edges. Criteria 1, 2, 3 and 6 — receipt-bound close/reopen, resumable PG/GitHub split, real external verification — remain open. Keep FA-029 open and say so in the commit message.