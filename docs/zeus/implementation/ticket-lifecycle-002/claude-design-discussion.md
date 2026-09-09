Read the design. Verified the `TicketSuperseded` claim myself: all five handlers (`releases.py:105`, `deployment.py:57`, `executor.py:473` and `:552`, `workflow.py:135`) set a terminal `superseded` status and retain `result`/`error`; none re-queue or retry. My "handlers treat it as reassess and continue" assumption was wrong — the docstring's "reassessment required" text misled me, the code doesn't do that. `TicketClosed` as a subclass is the right call, and a new unrelated exception would indeed escape those evidence-preserving paths and propagate uncaught.

## Adjudication confirmed

The trust boundary is now sound for this increment. Out-of-band deployment anchor with no packet/CLI override, fixed policy path read from that immutable commit, PG pinning the first anchor and failing closed on mismatch, no unsigned rotation, Zeus never generating or holding a production human key — that closes the self-authorization loop I raised. The framing is also honest: an external bootstrap boundary is not a claim that the bootstrap proves human presence, and `configured_key_authority_only` carries that in the receipt rather than in a doc. Deferring authenticated successor rotation to before full production adoption, with validity/revocation fields enforced now, is a reasonable split.

Everything else I raised is accepted and correctly specified: separate packet-idempotency and sequence-uniqueness checks, verification outside a short PG commit, exact canonical bytes, generated principal-specific allowed-signers file with scrubbed environment, merged-commit ancestry, bounded time-bound artifact reads, explicit reopen before editing a closed ticket, sequence-zero legacy bindings and dispatch IDs retained.

## Five small items to settle in code, none blocking a start

1. **Reject incomplete signature sets; never accumulate partial approvals.** The design says required signers must all be present but not what happens to a submission carrying 1 of 2. If partial sets are stored as pending, that store becomes a new surface where a later submission completes an older packet under a since-changed policy. Verify all required signatures in one invocation and reject outright otherwise — no pending-approval table.

2. **State that the signed bytes exclude the signature envelope.** With N signers all signing identical bytes, the packet digest must be over the packet alone, with signatures stored beside it. Worth one line in the design because getting it backwards makes multi-signer impossible and would be discovered late.

3. **Anchor-absent behavior.** Define it explicitly: if deployment configuration supplies no anchor, fail closed rather than falling back to the PG pin, so a misconfigured deploy cannot close tickets. Also record the provenance of the first pin (when, by which configuration) — it is trust-on-first-use by construction, and that should be visible in the ledger rather than implicit.

4. **Enforce validity and revocation in Python against `issued_at`, not via `-Overify-time`.** That keeps the OpenSSH floor at 8.2 (`-Y verify`) instead of 8.8, which matters on Windows, and makes the window logic deterministic and unit-testable without a real clock dependency.

5. **Confirm reopen is unsigned, and say why.** The design implies it ("recorded explicit local transition"), and it is safe — reopen only removes authority, and the subsequent close needs a fresh packet at the new sequence — but it should be stated rather than inferred. If reopen ever becomes signed, reserve `zeus-ticket-reopen-v1` now so a close signature can never replay as a reopen.

Minor, optional: requiring `issued_at >= ` the ticket revision's `updated_at` catches "signed before the approved content existed" independently of the content hash, and costs one comparison.

## Go

Proceed with implementation. The trust-anchor and replay questions are adjudicated, the five items above are specification details rather than design changes, and #30 staying open with acceptance on isolated PostgreSQL plus a separately marked GitHub test issue is the right scope. FA-029 stays open until that acceptance run lands.