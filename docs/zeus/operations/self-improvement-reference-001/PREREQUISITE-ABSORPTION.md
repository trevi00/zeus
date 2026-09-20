# Prerequisite-aware experience: bounded reference adaptation

Continuation of SPEC.md, 2026-09-20. Status: bounded adaptation accepted and integrated
in the task branch; not deployed to the operating image.

## Decision and source

Adapt Hermes's separation of prerequisites, pitfalls and verification into the existing
Zeus worker profile. Extend the existing authority rather than installing another skill
manager. This is a prompt-level adaptation backed by a real local incident, not an
upstream preflight engine or proof of model compliance.

Pinned Hermes source: `59f9ff8dbc75b9c4f07ae10174df730f7882a505`.
`agent/learn_prompt.py:43-52` describes explicit prerequisites and verification;
`:172-190` prefers updating an existing skill and incrementally preserving large sources.
`hermes_cli/cli_commands_mixin.py:1906-1914` queues the generated prompt as a normal turn.
`tests/agent/test_learn_prompt.py:46-108` asserts prompt content. Upstream tests were read,
not run. No upstream executable was installed or source code copied.

Source blob: `db50f95aa3196fb19f265d0491ca93f63b4f2c84`.
Source SHA-256: `14529273cc4c1f371e9f2843cfd5a1ced9c3bba16acc6304d418b1f8a38f12c1`.
This exact provenance is added to the existing packaged profile manifest.

## Local evidence and affected path

The prior baseline amendment worker produced a valid narrow change but could not run
its historical Git comparison in a snapshot checkout. It attempted several unavailable
alternatives before reporting failure. Fleet correctly refused the evidence; the owner
later verified the candidate with actual Git history. See AUDIT-CANARY.md. The failure
does not prove that every worker check needs Git history or that the policy was wrong.

Zeus path: worker-profile-v1.md -> manifest digest -> load_profile -> Claude CLI
append-system-prompt / isolated profile binding -> profile-identified hook receipts.
The loader already rejects stale/oversize/unknown profiles. The profile already owns
authority, two-strike, reporting and verification guidance. This change adds the missing
prerequisite-specific lesson there, preserving the 6000-character cap and permissions.

Expected behavior: available checks proceed; a known missing prerequisite is named with
the affected check, evidence and the owner's required input/environment. Do not disable
the check, invent historical data, widen permissions or use ad-hoc test probes to bypass
the boundary. Guidance is not an enforced block or a proven behavior change in a model.

## Delivery and validation scope

Fleet job: `self-improvement-reference-001-prerequisites`.
Worker task: `0c500ac5-1b27-52cb-9ae8-1b01ff243c9c`.
Allowed change: profile document, its manifest, existing provenance-set test expectation.
No new runtime module, hook, scheduler, release, model routing or global configuration.

Run existing profile and metadata checks, exact metadata helper and ruff. These exercise
load/hash/size/rejection and subprocess protocol delivery; protocol fixtures are not a
live Claude adherence test. The previous full-suite run covers unchanged runtime only.
No new WSL/upstream integration claim. Final candidate and observed results follow below.

## Candidate and owner checks

Candidate `f80fdd37c662e509640026783e71438348a6effe`; isolated worker run
`49ac15c2ec4d4cb694a483a6df54ab5a`. Three allowed files changed. Compression retains
the authority, critical-only scope, repeated-failure, verification and reporting rules;
the new prerequisite paragraph fits within the existing cap. Prior permissions, hook
digest and all 12 source entries are unchanged; the thirteenth entry pins Hermes.
The existing manifest-count test necessarily changes 12 to 13 alongside the source set.
No other test logic, runtime module or hook implementation changes.

Worker-reported container checks: profile/metadata 50 passed; affected two-strike and
project delivery checks 17 passed; ruff passed. Initial metadata runs reported stale
digest/oversize while editing; these are preserved diagnostic failures, not final passes.
The worker's retained inner_result.json SHA-256 is
`99adc7de3d9111339e2eda8f64fecac7ed8174fd4bf91d373a5f0e4907e7e5a2`.

Owner independently reran all four affected test files on Windows: **65 passed, 2 skipped**,
exit 0, 11.58 seconds. Skips: this host cannot create the symlink fixture; POSIX sh is
unavailable for the command-text execution fixture. Metadata exit 0: 5985 characters,
document and hook digests match. Ruff exit 0. No full suite rerun for this data-only change.
These protocol/metadata checks do not prove real-model compliance with the new guidance.

Evidence root: `D:/workspaces/zeus/artifacts/self-improvement-reference-001/prerequisites-verification-001`.
receipt.json binds candidate, commands, exits and log hashes. Pytest log SHA-256:
`0bc60ede0be13410b376d994bc53f071e4baf8b3647cb091deb152ab40328fbf`.
Profile document SHA-256: `807092b822dbb198f1fb3d9d694dbd7f767fbd0c01686b87701f602272aa19c9`.

## Final disposition

Independent Codex decision `d3d02112-04b5-497d-9e5e-cee62ea932f0` accepted the exact
candidate with no material findings. Preserved evidence inspector checked 4/4 command
claims without mismatches. Decision execution reference:
`sha256:679bde519de42a0258b85f892bdd4bfc5be544c02617d2810f06266af95df492`.
Fleet job finished accepted/lead_accepted. Owner independently accepted the source mapping,
whole diff and host checks, then integrated the candidate into the existing task branch.

Completion means this single lesson is packaged with provenance and verified delivery
contracts. It does not mean all Hermes skills were absorbed, a machine prerequisite gate
was added, models demonstrably obey it, or retry rates improved. No main merge, operating
image update or global activation occurred. This bounded worker/reviewer run is complete;
no automatic successor was enqueued by this task.
