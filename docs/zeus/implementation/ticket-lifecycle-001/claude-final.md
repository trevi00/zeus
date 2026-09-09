All four fixes are present and correct as described. Verified against the code:

- `_observe` (`:43-53`) is content-addressed on `{ticket_id, repository, evidence_ref, purpose}` with `first_seen` retained and `at` refreshed; `test_identical_sync_observations_are_bounded` correctly lands on exactly 2 rows after 4 syncs (pre_write and post_write of an identical remote differ only by purpose).
- `dispatch` (`tickets.py:155-159`) embeds the last 10 with explicit total/omitted while the table keeps all 16 — the test asserts both halves, which is the right shape.
- `:77-79` enforces `expected_revision` unconditionally and makes it mandatory for reconcile.
- `:126-127` scopes `previous_title_hash` to `link and "title_hash" not in link`, and `test_legacy_link_does_not_trust_an_arbitrary_observed_title` pins the rejection side — that test is what gives the rule teeth.
- Creation receipts (`:163-168`) are written to `ticket_remote_creations` keyed by `digest(creation)` *before* the ownership-gated `ticket_syncs` write, so lease expiry loses only the cache. Keying on the digest including `claim_owner` is right: same-owner retries are idempotent, and two owners recording the same number collapse in the `numbers` set at `:89-92` rather than tripping the `<= 1` guard. Known numbers are consulted before the search index (`:96`), and `test_create_ack_after_lease_expiry_is_retained_for_recovery` drives exactly that path with `indexed=False`.

## One defect

**Reconcile authorization leaks past a failed attempt via `observed_*_hash`.** At `:144-145` the pending transaction records the *pre-write* remote hashes unconditionally. On the reconcile path that content is, by definition, the foreign body/title the operator asked to overwrite. On success `:200-202` overwrites them with the post-write projection, so nothing leaks. But if the sync fails after `:141` — edit unreachable, readback mismatch, lease expiry — the `except` handler preserves the row, leaving `observed_body_hash` set to the external body's hash.

A subsequent **plain** sync then passes `:122` (`remote_hash in {..., observed_body_hash}`) and overwrites the external content with no `reconcile_observation`, no observation-equality check, and no revision binding — even if the ticket revision has since changed. The one-time, revision-bound authorization silently becomes a standing one. Note also that `:146` persists `reconcile_observation` into `ticket_syncs` but nothing ever reads it back, so the recorded intent isn't enforcing anything.

Narrow fix — don't fold explicitly-foreign content into the accepted set:

```python
"observed_body_hash": digest(issue["body"]) if issue and not reconciled else current.get("observed_body_hash"),
"observed_title_hash": digest(issue["title"]) if issue and not reconciled else current.get("observed_title_hash"),
```

(`reconciled` needs hoisting to `False` before the `if issue:` block at `:108` so it's defined when `issue is None`.) A test for it: reconcile with an unreachable `issue edit`, then assert a plain sync raises "changed externally" rather than proceeding.

## Notes, not blockers

- A genuine double-create makes `:93` (`"Multiple remote creation receipts"`) a permanent stop with no operator command to clear it — `reconcile_observation` can't help because the raise precedes discovery. Safe (it cannot compound), but the only escape today is a manual store edit. Worth a follow-up path.
- `record["content_hash"]` is now `None` when the first-ever sync hits `state_conflict` with no link (`:182`). Harmless in these files (`:87` degrades to `previous = None`), but confirm no consumer treats `ticket_github["content_hash"]` as always present.
- `Tickets.get` still returns every observation while `dispatch` is bounded. Intentional retention, but `ticket show` output now grows one row per distinct external state forever.
- `marker_present` on observations is a good addition for the reconcile-onto-a-hijacked-number case; it stays advisory, which is the right call.

## Approval

Approved as an incremental fix, conditional on the `observed_*_hash` reconcile leak above. It delivers FA-029 acceptance criterion 5 and the criterion-4 ACK/ownership edges. Criteria 1, 2, 3 and 6 — receipt-bound close/reopen, resumable PG/GitHub split, real external verification — remain open and unclaimed; keep FA-029 open and say so in the commit message.