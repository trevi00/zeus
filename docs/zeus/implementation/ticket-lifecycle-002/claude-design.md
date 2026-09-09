Read the current `ticket_binding`/`dispatch`/`update`, `github_tickets.sync`, and the existing Git-pinned-policy precedent (`sdd.py:32-47`) and `GitSourceVerifier` for how this codebase already reads Git objects without checkout. The design is sound in shape — content-addressed packet, fail-closed policy, sequence-bound lifecycle, separate resumable remote sync. Below are the things I'd fix before implementation, ordered by severity.

## Blockers

**1. The trust policy is inside the repo the lifecycle closes tickets about — this is a self-authorization loop.** `.zeus/ticket-trust.json` at a Git path means anyone who can land a commit can enroll their own key as a human-role signer and then self-approve closures. That relocates "no authenticated human provider" to "whoever can push", it doesn't solve it. Zeus's own dispatch→implement→release flow writes to this repo.

Pick a chain of trust: each trust-policy revision must itself be signed by a quorum of the *outgoing* policy's human signers, with the trust-revision lineage stored append-only in PG and anchored to one out-of-band bootstrap revision established once by an operator. Minimum viable version if that's too much for this increment: record `trust_policy_commit` in every closure decision and refuse any closure whose trust policy commit differs from the anchored one without an explicit `trust-rotate` decision. Without one of these, the signature layer is decorative.

**2. Pin the policy commit, not just HEAD.** "Fixed Git HEAD path" is mutable between packet issuance and PG commit. Follow the `read_spec` precedent (`sdd.py:36-43`): resolve `rev-parse --verify <rev>^{commit}`, read via `git show <pinned>:<path>`, and record both `policy_commit` and `policy_hash` in the packet *and* the decision. Rechecking only the hash under PG can't distinguish "same policy, different commit" from a rewritten history.

**3. Packet single-use needs two distinct PG constraints, not one.** Content-addressing the decision on `digest(packet)` gives idempotent retry but does not prevent two *different* valid packets closing the same sequence (e.g. two signers each issue one). Add a unique constraint on `(ticket_id, lifecycle_sequence)` for close decisions. Both are required; neither alone is sufficient.

**4. Reopen idempotency key must include the source sequence.** If the key is `digest(request)` over `{ticket_id, revision, reason}`, a replayed reopen after a subsequent close returns "already applied" and reports success while the ticket is closed. Key it on `{ticket_id, from_sequence, revision, reason}` and require `from_sequence == current` inside the transaction.

**5. `ssh-keygen -Y verify` specifics that decide whether this works at all:**
- Generate the `allowed_signers` file into a temp dir from the loaded policy at verification time. Never read one from the repo or `~/.ssh`, and run with scrubbed env and an explicit `HOME` so no ambient agent/config grants authority.
- Verify **per principal** with `-I <principal>`, not "some signer in the file". You need to know which principal signed to evaluate `required_signers`, and you must confirm the matched key equals the enrolled key.
- Distinct namespaces per operation: `zeus-ticket-close-v1` and `zeus-ticket-reopen-v1`. A single shared namespace lets a close signature replay as a reopen authorization.
- Feed the exact canonical bytes on stdin, store those bytes as an artifact, and hash *those* — never re-serialize between signing and verification.
- `-Y verify` requires OpenSSH ≥ 8.2 and `-Overify-time` ≥ 8.8. On win32 this is a live portability risk; detect the version and fail closed with a clear message rather than misinterpreting an error exit.

**6. Commit existence ≠ the work is in the tree.** `cat-file -e <commit>^{commit}` passes for an abandoned branch's commit still in the object store. Either require `merge-base --is-ancestor <commit> <named ref>` and record the ref, or state explicitly in the decision that reachability is not claimed. Given the acceptance-criteria wording, I'd require ancestry.

## Specifications to nail down

- **Fail-closed must cover malformed, not just absent.** Reuse `parse_json`'s duplicate-key rejection (`sdd.py:22-29`). Reject at load time: duplicate principals, the *same key under two principals* (one principal impersonates the other toward `required_signers`), key types outside an allow-list, `required_signers` ⊄ enrolled, and empty `required_signers`. "≥1 configured signer" has to be a policy-load invariant, not only a count at decision time.
- **Key validity and revocation.** Support `valid_after`/`valid_before` and a revocation list; bind `-Overify-time` to the packet's `issued_at`, and additionally require `issued_at` to fall inside the policy's window as of decision time. Otherwise a revoked key stays good forever for old packets.
- **Bound the grant window.** Require `issued_at <= now`, `expires_at - issued_at <= 24h`, and `issued_at >= ` the ticket revision's `updated_at` — the last one catches "signed before the approved content existed" independently of the content hash.
- **Define "stale" evidence concretely** or it's unenforceable: artifact whose source revision predates the solution commit, or whose bound ticket revision ≠ the packet's revision.
- **Evidence refs**: each must resolve through the integrity-checked artifact read at verification time, must not be a closure/packet artifact itself (no self-referential evidence), and should carry a total-bytes budget mirroring `artifacts.text`.
- **Bind the AC list as a whole** — include `digest(content["acceptance_criteria"])` and the count alongside the per-index hashes. It's implied by `content_hash`, but the explicit check makes the failure legible instead of surfacing as a hash mismatch.
- **Verify outside the transaction, re-check identity inside.** Don't run `ssh-keygen` subprocesses inside a PG transaction. Produce a verification receipt artifact, then re-check `(revision, content_hash, status, lifecycle_sequence, policy_commit, policy_hash)` in a short transaction.
- Put the limitation on the record, not only in docs: `attestation_scope: "configured_key_authority_only"` travels with the receipt.

## Integration edges in existing code

- **`ticket_binding` is a compatibility event.** `tickets.py:35` demands `set(bound) == {"id","revision","content_hash"}` exactly; every persisted binding in plan/rework/review envelopes, `promotion_intents` and `ticket_dispatches` uses that 3-key form. Your "legacy binding valid only at sequence 0" rule is right and enforceable — but note `dispatch`'s key is `digest(bound)` (`tickets.py:145`), so adding sequence changes the id and defeats the `previous` idempotency check at `:146`, re-queueing an outbox message for already-dispatched sequence-0 tickets. Either include sequence in the key only when `> 0`, or dedupe on `(ticket_id, revision, sequence)`. Say which.
- **`TicketSuperseded` is the wrong signal for "closed".** Downstream handlers presumably read it as "reassess and continue". A closed ticket should stop work, not trigger rework. Use a distinct exception and check the handlers.
- **`update()` already silently reopens.** `tickets.py:85-86` sets `status="open"` unconditionally on every revision edit. So "revision edit of a closed ticket reopens and increments sequence" isn't an addition — the implicit, unsigned, reasonless reopen exists today. I'd make `update` on a closed ticket *refuse* with "reopen before editing", mirroring the promotion-intent guard at `:80-83`, so the lifecycle stays the only writer of `status`.
- **Sync**: `desired_state` is a hardcoded literal at `github_tickets.py:134`. Deriving it from a verified decision is small, but the write branch at `:149` must issue a state call (`issue close`/`reopen`) rather than `issue edit`, and the readback `require` at `:175-177` — currently gated on `not state_conflict` — must cover state as well as body/title when a write was attempted. Carry the authorizing decision id in `record["desired_state"]`'s neighborhood so the receipt is self-justifying. The existing invariant that a manual remote CLOSE against an OPEN desired state is a conflict survives unchanged, which is the right outcome.
- The 300s lease now spans one more 60s call. Confirm the renewal at `:142` still covers read + state call + readback.

## Tests and scope

Negative cases that are easy to get wrong and worth writing first: signature over a near-identical packet with one AC outcome flipped; valid signature by an unenrolled key; enrolled key with the wrong principal string; two signatures by the same principal counted once; a signature valid in the test namespace rejected in the production namespace; an enrolled non-human role failing `required_human_signers`. Name test principals unmistakably (`test-only-not-a-human@zeus.invalid`) and assert no record claims human attestation.

Agreed on leaving #30 open and using a separate marked test issue. Note FA-029's criterion 6 also requires *actual PG* — so that run needs the real store, not `MemoryStore`, to count.

FA-029 remains open; this design, once the trust-anchor question above is answered, is what would close criteria 1–4 and 6.