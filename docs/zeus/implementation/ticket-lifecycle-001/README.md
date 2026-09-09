# Ticket projection correction

The user redirected work from further review batches and issue registration to
fixing reviewed defects. Full source analysis remains in scope; it no longer blocks
implementation of an already reviewed problem. No new issue was registered here.

The original adapter could report `synced` for a manually closed issue, miss an
external title change, or trust a successful edit response without checking the
result. Three new behavioral regressions failed against that implementation
(tool `5c8e42`). Root and actual Claude reviewed the design before the adapter edit.

The adapter now records remote observations before rejecting conflicts, compares
title and body, reads the remote issue after a write, and checks local revision,
content, status, reviewer set and lease ownership before recording success. An
external CLOSED state produces `state_conflict`; it never creates local acceptance
or automatically reopens the issue. Failed synchronization invalidates a previous
`synced` link. A successful create's issue number is retained before readback so
readback outages do not force rediscovery through the search index.

An explicit title/body reconciliation uses a saved observation and the current
ticket revision. New external changes invalidate the request. Inspect the output
of `zeus ticket pull TICKET --repo OWNER/REPO`, then use its observation `id`:

```text
zeus ticket sync TICKET --repo OWNER/REPO --revision REVISION --reconcile-observation OBSERVATION_ID
```

This replaces only the observed title/body with the local projection. It does not
grant release approval, close an issue, or overwrite later external edits knowingly.
GitHub operations and PostgreSQL commits are separate; a late remote write cannot
be physically fenced by this adapter's local lease. Its result cannot become a
successful local receipt after loss of ownership. Retained observations and the next
sync expose discrepancies. Exact remote text is compared; unverified normalization
is not used to turn a mismatch into success.

Legacy links recover the known title from their versioned local ticket rather than
trusting an arbitrary first observed title. Search discovery obtains a full issue
read; the tests now model the actual requested list fields instead of accidentally
supplying title/state to a list request that did not ask for them.

Validation is split by boundary. The final targeted 56 tests passed with both memory and
isolated real PostgreSQL storage (`933734`, 24.75 seconds); the GitHub transport in these tests is
replaced to exercise failures deterministically. This is not real GitHub acceptance.
`live-readback-final.json` separately records actual PostgreSQL plus actual GitHub issue30
readback, preserving its original title/body/comments/OPEN state. No real improvement
issue was closed as a test. The earlier PG test attempt failed because the preview
test assumed MemoryStore.data; it now compares the common transaction record API.
The initial live readback and intermediate Claude findings are retained unchanged.

Actual Claude reviewed the design, patch and corrections in session
`2dc41532-c263-4a29-8689-c8b385e1da27`; the prompts, raw responses, extracted reports
and process receipts are alongside this document. Root implemented all changes and
adjudicated the findings in `resolution.md`. Claude's final correction review has
no blocking findings. This is code review, not human acceptance or deployment.

FA-029 remains open: criterion-by-criterion evidence-bound close/reopen decisions,
authenticated required human approval, resumable state-changing projection and its
real external failure/recovery acceptance are still required. This correction does
not replace that scope with a narrower definition of completion.
