# Codex consumer and test follow-up

The original golden runner's load_cases accepts only truthy-command dict entries but
does not enforce a list root, required case identities or a complete schema. It validates
expect_exit after spawning the command. run reports retained cases only. gate explicitly
permits zero cases, curator's _golden_gate uses that result, and quality_cmd exits from
failure count alone. The separate golden smoke requires total >=8 and at least one
held-out case; that defense is not present in those runtime consumers. The smoke was
freshly read but not executed: it also calls actual source cases, curator, router and a
mutation runner beyond this batch's reviewed execution boundary.

Expected-output suppression for held-out failure messages and a router test excluding
the golden directory are real narrow defenses. They do not authenticate independent
test ownership or restrict every model's filesystem reads. The source nine-case list
has three held-out flags; stale count comments are not its authoritative denominator.
Fixture probes test deterministic synthetic inputs, not independent human acceptance.

The tests README's residual flat-glob warning is obsolete in this pinned code:
sandbox.run_suites imports CANON_GLOB and rejects initial zero discovery. Its limited
only-filter can return empty after matching no selected names, a separate reconfirmation
contract with caller scope still to trace. Do not re-report the old default as current.
The selected run_suites code checks process exit and carries caller environment; it is
not an OS sandbox. test_isolation checks substring presence rather than execution/import
order. isolation_fitness reports inability to inspect Git but returns an empty issue list;
that must remain visibly uninspected rather than inferred portable. Ownership checks
actually consume directory existence, so the tracked marker READMEs have a real purpose.

The researcher loop preserves per-source records and only refreshes its heartbeat when
ok_sources is nonzero. Its fleet health probe nevertheless covers just that one path,
not each queued/supervised stage. The complete dba_projection body checks missing ledger
and sync exceptions, but a successful sync reporting no events logs a message and still
refreshes heartbeat/returns zero. It does not enforce the neighboring comment's nonzero
stage premise. Its contract test substitutes a fake projection module and was not run;
it establishes neither real PG failure behavior nor exact database/source parity here.

Chat seeding is an actual consumer: for an armed chat pipeline it reads the two fixed
filenames, strips frontmatter by string splitting and caps each body at 1200 characters.
It does not check trust/author fields in that function. The index's chat node builder
filters kind and defaults provenance but does not establish authenticated author identity.
These are bounded source findings, not evidence of malicious instructions or an observed
live prompt injection. No chat session or private conversation was inspected.

All source execution was limited to the directly reviewed isolation helpers and golden
runner over scratch fixtures. Unread transitive ranges, runtime qualification, model
evaluation, licenses, real service/device/human acceptance and adoption remain pending.
