# Authoring a durable guidance unit

**Purpose.** Make guidance readable and keep exactly one canonical owner for each rule.
**Owner:** the maintainer of the subject the document describes. **When to read:** before adding a
guidance document, before copying a rule into a second place, and before editing a packaged
document that carries a digest.

## One canonical definition

Write a rule once, in the document or module that owns it, and link it from everywhere else. A
restated rule is a second source of truth that will drift: prefer a sentence that names the owner
(`docs/contracts.md` INV-…, `domain/policy.py`, the packaged manifest) over a copy of its content.
When you find a duplicate, fix the copy rather than adding a third version, and say in the change
which one is now canonical.

## Predictable sections

A durable unit states, in whatever order reads best:

- **Purpose and owner** — what it decides, and who maintains it.
- **When to read** — the situation that should bring someone here.
- **Authoritative definition** — the code, contract or resource that actually enforces it, when
  something does.
- **Procedure** — the steps, in plain connected sentences.
- **Prerequisites** — the checkout, history, tools or services the procedure assumes, so a missing
  one is reported rather than worked around.
- **Evidence and verification** — the commands that show it worked, and what their output means.
- **Limits** — what is explicitly out of scope, unverified or unknown.
- **Related links** — pointers, not authority.

Short subjects get short sections; omit a heading rather than padding it. Use complete sentences
and expand compressed slash lists when the expansion is clearer. Length is not a target: a
document that fits its allowance with nothing invented is finished.

## Experience and lessons

An experience note binds to its evidence: the source revision or content hash it was read from,
the incident or run that was observed, the conditions under which it applies, and whether it is a
candidate or verified. Re-reading a note is not a recurrence, and a corrected source supersedes
the note written against it. Mark superseded notes as superseded instead of deleting the history.

## Packaged documents carry metadata

A document that is delivered to a provider is pinned by its manifest, so editing it is a two-step
act. For the worker profile:

1. Edit `src/codex_harness/resources/worker-profile-v1.md`.
2. Run `python -m codex_harness.adapters.worker_profile_metadata` from the checkout root with no
   arguments; it reports the normalized character count, the 15000-character limit, the computed
   `document_sha256`, the hook digest and whether the manifest agrees.
3. Copy the reported digest into `worker-profile-v1.json` with Edit and run the command again; exit
   0 means the manifest matches.

The limit is a ceiling for that one common document, verified by `worker_profile.load_profile`,
which refuses an oversized or mismatched document whole rather than truncating it. It is not a
token allowance, and it is not the budget of any other context: the per-run project section, the
project-skill selection and the research paths keep their own separate limits.
