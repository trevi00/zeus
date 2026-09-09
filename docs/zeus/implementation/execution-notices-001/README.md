# Transactional execution notices (FA-017 / GitHub #18)

This slice adds informational execution transition records and an outbox envelope
in the same PostgreSQL transaction as failure, containment, cancellation, or recovery.
Delivery is at least once. A retained inbox receipt makes repeated consumption
idempotent; a notice cannot authorize a review, release, or new task.

The baseline records a real PostgreSQL failed task with no outbox notification.
The initial kill matrix uses actual PostgreSQL, Redis, and four forcibly terminated
child processes: before commit, after commit, after publish, and after consumption
before acknowledgement. It exercises persistence and transport, not model execution
or human acceptance. `kill-tests.log` and its initial matrix precede subsequent
review fixes; they are not final-source validation.

Claude independently reviewed design, implementation, and the revised source.
The design prompt's implementation wording referred to the root's work; Claude's
invocations were restricted to read-only review. The root implements the changes.
Review receipts retain actual session IDs and output hashes.

The final review's proposed outbox test edits require individual adjudication:
successful business paths and rollback tests must retain their original assertions.
Only transitions that now produce a notice should distinguish notices from business
commands. Storage failures must still roll back the entire transaction.

The first complete Windows run found 40 failing assertions after adding notices
(`superseded-full-tests.log`). Root changed only the observed failure/blocked paths
to require exactly one notice with the expected reason or state. Stale-owner paths
still require an empty outbox. A failed decision business commit must still leave
no business effects; its separate failure transaction now produces one notice.
Unrelated successful-path and rollback assertions suggested by review remain intact.

Quarantine uses semantic transition fields rather than mutable clock/error metadata.
JSON-compatible source data is retained; otherwise unencodable values are explicitly
represented by type labels and mixed-key mappings by entries. Tests exercise storage
of this representation in both memory and actual PostgreSQL, including repeated
observation with changed wall-clock metadata. This is not a promise to serialize
arbitrary cyclic Python object graphs; persisted runtime records are JSON.

After those fixes, targeted Windows verification passed 169 tests with one skipped;
the additional memory/PostgreSQL decision atomicity matrix passed all 24 tests.
The corresponding final Windows kill evidence is
`kill-matrix-339c1cce3bd342068cf05ec7cd576f7a.json` (four child processes killed,
two actual Redis stream entries, one receipt, pending entry reclaimed).

Final Windows full regression: **821 passed, 237 skipped** (`full-tests.log`);
Ruff passed. Skipped integrations are not claimed as executed by that ordinary run.
Claude resolution review (`claude-resolution.md`, session
`a4d29972-1698-48a6-a194-b682d4584bd5`) found no blocking defect within this slice.
It did not execute tests. Its remaining observations concern cyclic/deep Python
objects and ambiguity of type labels for unencodable, non-JSON input.

This is not completion of FA-017 or pilot acceptance. No-state adoption/conflict
stalls, clock discontinuities, and the complete native execution/reconciliation
matrix remain outside this slice. No existing production container is replaced.
