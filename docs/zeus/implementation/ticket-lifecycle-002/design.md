# Evidence-bound ticket lifecycle

Root and actual Claude reviewed current Zeus code before implementation. This work
continues FA-029; it creates no new analysis issue. The previous projection fix is
825979da94c889bf9ece20ad814bef325d209ee4.

Closure accepts a content-addressed canonical packet, never an actor string. It binds
the ticket revision/hash and current lifecycle sequence/status, all acceptance
criteria by index and text hash, the merged solution commit, environment and
criterion evidence, bounded grant times, trust-policy commit/hash and scope. Every
criterion must pass and every artifact must exist with its exact digest. Enrolled
signers attest the exact packet; signatures do not independently prove that tests
are sufficient or that a human was physically present. That limitation travels in
the receipt as configured_key_authority_only.

Claude correctly rejected loading trust from mutable Git HEAD. The implementation
will require an out-of-band deployment trust commit, with no packet/CLI override,
and pin that anchor in PostgreSQL. The policy remains a Git definition at the fixed
`.zeus/ticket-trust.json` path, read from that full immutable commit. Repository
changes cannot enroll a new approver. An anchor mismatch fails closed; unsigned
rotation is unavailable. Initial trust provisioning remains an operator boundary:
Zeus never generates a production human key or signs on a person's behalf. Temporary
test keys establish only test automation identity. Key validity and explicit revoked
principals are enforced from the pinned policy; rotation/revocation updates require
an authenticated successor policy before production adoption is complete.

Signatures use OpenSSH verification with a generated, principal-specific allowed
signers file, a scrubbed environment and exact canonical packet bytes. Duplicate
principals/keys, unknown signers, malformed policies and missing required signers
are rejected. Windows real OpenSSH sign/verify and modified-payload rejection were
verified with an ephemeral test key (`0e90da`); no private key was retained. The
protocol reference is https://man.openbsd.org/ssh-keygen (-Y verify).

PostgreSQL records the closure decision and pending remote projection atomically.
Packet idempotency and ticket/source-sequence uniqueness are separate checks.
Reopen binds its source sequence and reason; later close/reopen cycles cannot turn
an old retry into success. Revision editing a closed ticket will require explicit
reopen first. Lifecycle events retain hash-linked historical evidence. A new cycle
invalidates all old dispatches and acceptance packets. Sequence-zero legacy task
bindings and dispatch IDs are retained; nonzero cycles require an explicit sequence.

Root checked every existing TicketSuperseded handler: they stop/supersede work and
retain results; they do not automatically rework it. A TicketClosed subclass can
therefore communicate the reason while using those existing terminal paths. A new
unrelated exception would bypass their evidence-preserving handling.

GitHub state changes remain a separate resumable step. A close uses the persisted
valid decision; reopen uses a recorded explicit local transition. A manually closed
remote issue never creates local acceptance. Remote readback, lease and lifecycle
sequence checks prevent false success, without claiming a cross-system transaction.
Actual acceptance will use isolated PostgreSQL and a clearly marked separate GitHub
test issue; issue30 will stay open until all of FA-029 is satisfied.
