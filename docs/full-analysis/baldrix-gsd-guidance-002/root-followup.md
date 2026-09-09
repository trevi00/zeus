# Root consumer tracing and bounded conclusions

This additive follow-up follows fresh reading of all eight primary files and the listed
nine supporting files/ranges. No source code, profiling collection, session data, credential,
network, installation, original test or mutation command was executed.

## Profile data, consent and scoring

profile-user.md 59-121 contains a real consent choice, cancel path and questionnaire option;
241-263 presents contextual splits to the user. Preserve these defenses. However, its
89-95 display promises no external service transfer and automatic exclusion. The same
workflow 149-184 passes the sampled message file to a model agent, then stores its analysis.
Actual provider configuration/transmission was not inspected, so no real transfer is claimed;
the code path alone does not enforce the blanket promise.

profile-pipeline.cjs 107-155 filters record types and truncates messages; 392-539 samples
and writes their content plus session/project metadata. These read ranges have no content
redaction before the specified model input. Invalid JSON and per-session errors are skipped.
The first accepted messages are capped before later context/log exclusions. Recency uses
session mtime for a 10-versus-3 cap, while the rubric/agent subsequently weights message
signals approximately three times. The two denominators are different and can compound.
The per-project cap limits sessions, not each project's final number of messages, and the
global limit can stop before older projects. Agent claims of proportional sampling do not
follow from those loops. Zero selected messages can produce a returned output_file path
without the append loop creating the file. This is static, not a collected real-user result.

profile-output.cjs 475-644 accepts a dimensions object and truthy profile_version, not the
rubric's complete schema. Redaction iterates only dim.evidence at 527-537, but the renderer
prefers dim.evidence_quotes at 603, matching the rubric's declared output. Thus that path is
outside the selected redaction pass. summary/instruction/project labels are also rendered
outside it, and the pattern list does not cover Windows username paths. Layer-1 agent quote
exclusion remains a separate real instruction. Neither its compliance nor an actual leak
was measured. The output can say 'None detected' because redactedCount is zero, which is not
proof all fields were checked. HIGH/MEDIUM instructions are written from supplied confidence
without independently recomputing evidence counts. Existing UNSCORED/LOW fallbacks matter.

The profile workflow writes before its result-view prompt. A split choice updates rating
but does not explicitly regenerate claude_instruction; the writer consumes both separately.
The displayed highlight instructions name evidence while the declared agent schema names
evidence_quotes. These are consumer contract mismatches, not completed user acceptance.
User preferences are subordinate to current explicit instructions and never authorize
unrequested actions or qualify Astra/Sol/Terra on real scenarios.

## Workstream routing

gsd-tools.cjs 255-280 implements explicit --ws, environment and pointer selection, with
name validation. core.cjs 635-866 implements project/workstream paths, shared root resources,
TTY probing only on interactive input, canonical project paths and session pointers.
When a session key exists, missing/stale session pointers do not fall through to shared
state; the legacy pointer is read only without such a key. Preserve this narrower behavior.

Session tokens are sanitized and truncated to 160 characters, not hashed as opaque unique
identities. Different raw identifiers can collide after replacement/truncation. Reads may
unlink invalid/stale pointers; writes use direct writeFileSync without the inspected code
establishing an atomic rename/fenced lease. An inherited GSD_WORKSTREAM takes priority over
a newly selected pointer. Pointers validate .planning/workstreams/name while planningDir
can route under GSD_PROJECT, so the project dimension needs explicit reconciliation.
These are static limitations, not reproduced races or Windows/WSL behavior. Source text
about lightweight routing must not be promoted to PG ownership or acceptance authority.

## Overrides, verification, context and version

kha-verifier.md 165-219 repeats fuzzy matching and counts overrides as passed; its report
schema 589-607 includes the override count in the score. The reference preserves human_needed
and distinguishes an override visually. Exact scenario IDs, approved revision, actor,
expiry and explicit waived status are still needed before adapting that policy to Zeus.
No matching engine, actual verifier invocation or full promotion path was exercised.

verification-patterns.md preserves a valuable four-level model and actual user-flow checks,
but its grep and size heuristics do not prove wiring or business results. Listed env grep
would print matching values and snippets do not uniformly preserve command failure. The
direct loader of this particular reference remains unconfirmed; selected name searches
are not complete absence evidence. No listed snippets or external tool examples were run.

config.cjs 335-397 validates dev/research/review on config-set and reads raw config values.
This proves a configuration interface, not actual context Markdown loading; the latter
was not found in bounded searches. A search included a nonexistent hooks directory and
returned an error, and one broad result was truncated. Neither is counted as full search
coverage or proof that a loader cannot exist elsewhere.

update.md 195-243 uses VERSION with a workflow marker to choose local/global runtime and
has unknown-version/runtime branches. These are narrower than commit/hash qualification.
The 1.34.2 marker was read as source data; no update or installation ran. Only the listed
update interval was traced, not its entire multi-runtime detection or install closure.

Nine supporting records are excluded from primary coverage. Tests matching this narrow set
were not found by the selected name search under scripts/tests and bin/lib/__tests__; that
does not establish repository-wide test absence. Full transitive/license closure, current
external claims, original tests, real privacy guarantees, OS behavior, actual model/user
acceptance and Zeus adoption remain unverified.
