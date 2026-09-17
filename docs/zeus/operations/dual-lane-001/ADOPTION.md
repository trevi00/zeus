# Lane H adoption record — review-feedback principles in worker-v1

Status: INCOMPLETE. The document and the provenance entry are written; `document_sha256` in
`worker-profile-v1.json` is NOT updated and the character count is NOT machine-measured. The
worker session permits only `python -m pytest`, `python -m ruff`, `python -m compileall` and
read-only git, so no hashing or counting command could run (a `python -c` attempt was denied).
Until the owner sets the digest, `load_profile("worker-v1")` refuses this candidate.

Owner step: compute sha256 of the LF-normalized `worker-profile-v1.md` (the loader's
`_sha256`), confirm `len(document) <= 6000`, write the digest, rerun the focused tests. The
length was hand-estimated near 5,900-6,000 characters; treat that as unverified.

## Disposition

Improve the existing authority (`worker-profile-v1.md/json`); no second profile, loader, hook,
permission, test or runtime change. Source: `source.json` in this directory, appended to
`sources` with identical field values. Principles are rewritten; no upstream text or
executable is distributed. Rollback: revert both profile files together.

Adopted (new `## Review feedback` section): read the whole batch and map material findings to
the fixed criteria; a review assertion is not proof, check current code, callers, platform and
supplied evidence before editing; record supported disagreement or inability to verify without
claiming a fix, reviewer and owner keep authority; fix related confirmed material findings as
one batch and rerun affected checks; escalate only a consequential unresolved choice and
continue independent authorized work; report finding, evidence, disposition.

Rejected: stopping all work for any unclear item, item-by-item patch loops, gratitude/style
bans, the catchphrase.

## Condensation map (requirement kept, location or wording changed)

- Reporting bullet "reviewer accepts or rejects from the diff and recorded test output, not
  your summary; summary must be checkable" moved into the opening paragraph.
- Bug-investigation sentence "Nonblocking uncertainties stay follow-up notes; scope never
  expands automatically" split: follow-up notes joined the "Stop when the fixed criteria pass"
  bullet (now general); the scope rule joined Boundaries ("Never widen the scope yourself or
  automatically"). Both now apply to every task, not only defect work.
- Lead-escalation bullet gained "dependency"; the review section refers to it ("as above").
- "A search that finds nothing ... not proof that no implementation exists" became "An empty
  search is an unknown, not proof of absence". "full suite is the default" became "(the
  default)". "ordinary documentation or new-feature work" became "documentation or feature
  work". "not proof that the model adhered to them" became "not proof of adherence".
- Other edits are word-level shortening. Test-pinned phrases are unchanged: the
  "Verification before completion" heading, the `tests`/`summary` contract sentences, the
  host `project_evidence` exception and "Run tests as `python -m pytest`".

## Claims not made

This invocation ran under the OLD profile: no compliance or effectiveness claim for the new
guidance. Upstream MIT attribution remains an unverified document claim.
