# Root decision after independent Claude review

Root implemented the code after an independent design review and discussion with
actual Claude session `2dc41532-c263-4a29-8689-c8b385e1da27`. The immutable bootstrap
trust boundary, replay behavior, signer constraints, work-cycle invalidation and
separate remote state projection were adjudicated before implementation. All raw
review outputs and process receipts are retained alongside this decision.

Claude correctly found evidence without a wall-clock age bound, reusable remote
state-transition authority, ambiguous replay responses, unusable required/revoked
policies and missing required-signer lists in receipts. Root corrected these and
added tests. Signature armor accepts CRLF while retaining the original artifact;
canonical packet bytes are unchanged. Real Windows OpenSSH failed with code255
when PROGRAMDATA was scrubbed, and passed when that one required variable was
restored. This was measured with real signatures, not inferred from another OS.

Root independently found that validating closure before the sync try/claim allowed
an authority failure to leave a previous link `synced`. Verification now occurs
inside the claimed operation, outside PostgreSQL transactions, with failures recorded
as needs_attention. Claude agreed with that correction. Merely renewing after a long
verification would still expire; root added owned-lease renewal before each bounded
Git/SSH operation and before remote access. Claude's final review approved this.
Local artifact reads are byte-bounded, not time-bounded; if they stall long enough,
ownership expires and the next guard fails. The code does not claim physical fencing
of already-sent GitHub requests or a distributed PostgreSQL/GitHub transaction.

Root verified that TicketSuperseded handlers stop/supersede work and preserve results;
they do not automatically rework it. Claude withdrew the contrary initial assumption.
TicketClosed inherits those terminal paths. Reasserting OPEN deliberately starts a
new cycle, invalidating in-flight work and old acceptance even when the reason is
remote divergence rather than a genuine defect recurrence. That conservative effect
is documented and tested. A consumed close cannot override an external reopen; a new
local reopen and freshly signed acceptance are required to close again.

Every lifecycle chain is traversed before a transition or state projection. The
existing artifact text API was corrected to bound the file read before hashing;
the acceptance validator parses that same bounded string once. Evidence must use
canonical JSON. Signature validity is checked before verification, after its bounded
subprocesses and at the local closure commit. No private production key, partial
approval accumulator or unsigned trust rotation was introduced.

Final local validation: ruff passed; the Windows full suite passed 716 tests with
132 optional integration tests skipped (`31a9b2`, 280.42 seconds). The final lifecycle
suite passed all 80 cases with memory and isolated actual PostgreSQL, using actual
OpenSSH crypto (`a82c0f`, 79.40 seconds). Earlier broader targeted checkpoints passed
124, 140 and 148 cases and are historical checks before the final signer end-time
guard; they are not mislabeled as final-source validation. The initial implementation
failed three positive signature tests due to missing PROGRAMDATA, with 13 negative
tests passing; those failures are retained in the work log, not called acceptance.

Claude's final answer is code approval only. Actual separate-issue GitHub acceptance,
native WSL and remote CI are recorded separately when observed. No result here closes
FA-029 or supplies real human acceptance. Operational human enrollment and authenticated
successor trust-policy rotation still require completion before production adoption.
