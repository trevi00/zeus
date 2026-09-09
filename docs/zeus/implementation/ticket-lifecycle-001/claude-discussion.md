## Verdict

Approve the direction; the eight claimed behaviors are genuinely implemented and the new tests exercise real paths (the `--json` field projection at `tests/test_github_tickets.py:26-28` closes the discovery hole properly, and `test_legacy_link_uses_its_original_revision_title` really does drive the `previous_title_hash` branch). I accept your two disagreements: versioned-title recovery is stronger than trusting an observed legacy title, and exact-byte readback is the right default given 33 bodies matched exactly — the failure mode is a hard stop with a working reconcile escape, not corruption.

Four things should change before this lands. The rest are notes.

## Should fix

**1. Unbounded observation rows — the one real regression.** `_observe` (`github_tickets.py:43`) keys rows by `uuid4()`, and `sync` now writes `pre_write` on *every* sync (`:98`) plus `post_write` on every sync (`:154`), including the fully clean no-op path. Artifacts dedupe (content-addressed, `artifacts.py:26`) but the rows do not. `Tickets.get` scans and returns all of them (`tickets.py:105`), and `dispatch` embeds **all** of them into an authorized `task.assign` payload (`tickets.py:154-155`). Before this patch observations were only produced by explicit `pull`; now `ticket show` and every dispatch envelope grow ~2 rows per sync forever.

Fix: make the observation id content-derived — `digest({"ticket_id","repository","number","title","body","state","purpose"})` — so repeated identical observations collapse to one row. Optionally also skip the `pre_write` observation when the remote already equals the expected projection, computing divergence first and observing before the `require` so the preserve-before-conflict property is untouched. Independently, bound what `dispatch` embeds.

**2. `--revision` is silently ignored without `--reconcile-observation`.** `:72` only enforces the revision when reconciling, but the CLI exposes `--revision` on plain `sync` (`cli.py:231`). `zeus ticket sync X --repo r --revision 5` against revision 7 succeeds and syncs 7. Make it an unconditional guard:

```python
require(expected_revision is None or expected_revision == ticket["revision"], ...)
require(reconcile_observation is None or expected_revision is not None, ...)
```

**3. `previous_title_hash` is applied to modern links, not just legacy ones.** `:115` computes it whenever a link exists and `:116-118` adds it to the accepted set unconditionally. For a link that already has `title_hash`, this adds nothing except widening the accepted set. Scope it to the case it was written for:

```python
previous_title_hash = (digest(previous["content"]["title"])
                       if previous and link and "title_hash" not in link else None)
```

This also makes the design intent legible to the next reader, which matters because the rule is a deliberate departure from "trust the observed title".

**4. A known created issue number can still be lost.** `:150-152` persists `created_number` under `_owned`. If the lease expired during the `issue create` call, `_owned` raises and the number is discarded; the `except` handler at `:187` also refuses to touch the row when another owner has claimed it. The remote issue exists, the search index may not have it yet, and the next sync stalls on "Remote creation is uncertain". No duplicate — the invariant holds — but the stall is avoidable, and it's the residual lost-ACK gap.

The created number is a fact about the remote world, not a claim of ownership. Persist it in its own transaction without the ownership gate, appending to a `created_numbers` list so a concurrent owner's number is never clobbered, and have the discovery branch (`:85`) consider all of them.

## Notes

- **`needs_attention` is over-applied to benign races.** The `except` handler downgrades `ticket_github.status` (`:190-192`) for *any* exception after the claim, including `"Ticket changed before sync"` at `:127-128` — a concurrent `ticket update`, which is a plain retry. That makes `needs_attention` indistinguishable from genuine external divergence. Either restrict the link downgrade to failures raised after a remote read/write, or copy `error_type` onto the link so retryable races are separable.
- **Reconcile can overwrite an issue whose body no longer carries the marker.** `reconciled = True` bypasses both the body and title checks (`:111`, `:116`), and `_read` validates number/url/state but never the `<!-- zeus-ticket:... -->` marker. If a link's number were ever wrong or reused, reconcile would overwrite an unrelated issue. Requiring the marker is not possible (reconcile exists precisely for marker-less external bodies), so instead record `marker_present` in the observation so an operator sees it before naming that id. Low likelihood, cheap.
- **`state_conflict` computed twice.** `:123` uses the pre-write read, `:158` the post-write read, and `:155` gates the readback `require` on the stale value. Behavior is correct in all four orderings I walked, but the "conflict resolved between reads, write already skipped" case reports `outdated` with no indication a write was skipped. A `write_skipped` field on the record would make the receipt self-describing.
- `Tickets.get` sorts reviews and observations but leaves `github` links in scan order (`tickets.py:104`). Multi-repo links are nondeterministically ordered and the tests index `[0]`. Sort by `id`.
- Preview (`cli.py:251`) still does not display the API title as a distinct field, even though the title is now a compared, conflict-generating value. It only appears as the `# {title}` line inside the body.

## Test gaps worth closing

- **Legacy title rejection.** `test_legacy_link_uses_its_original_revision_title` only asserts the accept side. Without the mirror case — legacy link, no `title_hash`, remote title matching neither the current nor the original revision title, must raise — the implementation could degrade to "trust any observed legacy title" and the suite would stay green. This is the test that gives your disagreement with the naive approach its teeth.
- **`test_expired_lease_after_remote_write_cannot_record_success`** asserts no link and a retained observation, but not the recovery that makes the design safe: `ticket_syncs[key]["created_number"] == 7`, and a subsequent sync with `state["indexed"] = False` succeeding with `creates == 1`.
- **`test_external_title_change_is_preserved_and_invalidates_synced_status`** verifies the conflict and the link downgrade but never that the external title was captured before the raise — which is the headline claim of "observations before conflicts". Assert `external_observations[-1]["title"]` and that the artifact round-trips it.
- No test covers `state_conflict` on first discovery (no prior link). That path writes a record with `synced_revision: None`, which the next sync feeds into `f'{ticket_id}:{link["synced_revision"]}'` at `:81`. It degrades safely to `previous = None`, but nothing pins that.

## Scope

This is an incremental fix and I am not treating full FA-029 as a condition of approval. What it delivers is acceptance criterion 5 (observe external state/title changes, flag conflict, never fabricate acceptance — `:122` and `test_remote_manual_close_is_a_conflict_not_local_acceptance` back this) and most of criterion 4's ACK/ownership edges. Criteria 1, 2, 3 and 6 — receipt-bound close/reopen, resumable PG/GitHub split, real external verification — remain open and unclaimed. Keep FA-029 open and say so in the commit message.