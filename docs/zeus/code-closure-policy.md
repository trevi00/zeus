# Local code-defect closure policy

Provisioned at the user's request on 2026-09-11 to complete verified issue closure.
`.zeus/ticket-trust.json` enrolls an **automation** signer, not a human signer.
Its public key can attest exact-revision code-defect acceptance packets. The private
key stays outside Git under the current Windows user's restricted operator-key directory.

This does not grant human acceptance or deployment approval. All criterion evidence
must still be checked. Do not use this policy to claim a human decision, device test,
host interruption result, model qualification, or any unexecuted acceptance condition.
The policy scope is descriptive; the existing validator does not interpret the text
as an issue allowlist. The operator must restrict signing to reviewed code-defect packets.

The immutable policy commit must be set out of band as `ZEUS_TICKET_TRUST_COMMIT`.
No mutable HEAD fallback or new closure bypass is introduced. The first closure pins
the policy in PostgreSQL; changing a Git file or environment value thereafter cannot
rotate the pinned authority. The key expires after 90 days. Authenticated rotation
remains separate work; expiry must never be bypassed by editing runtime records.

Initial closure batch candidates: issues #2 through #9. Each requires its source and
Claude/Codex review references plus current Windows/Linux and relevant PostgreSQL
verification to be mapped to the exact existing acceptance criteria. Other issues
remain open until their own criteria have been verified. In particular, source review
or a fixture result does not satisfy a required human/device/host acceptance test.

Closure is performed through `TicketLifecycle.prepare/close` and `GitHubTickets.sync`,
retaining canonical packets, real OpenSSH signatures, PG lifecycle events and GitHub
readback. A plain remote CLOSED state is never used to invent local acceptance.
