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


## Repeated work becomes reusable capability

User direction, 2026-09-21. Owner: Codex for analysis, design and acceptance; Claude for the
specified implementation and tests. This is a working rule, not evidence that an automatic
recurrence detector or runtime skill publisher has been installed.

After two distinct executions of the same or materially similar procedure, record an automation
candidate, whether the executions succeeded or failed. Count task/run identities, not replayed
events, copied receipts, rereads, or repeated imports of one experience. Similarity is a hypothesis:
compare outcome, inputs, prerequisites, steps and verification before merging different procedures.
Keep the existing failed-tool two-strike research rule separate; successful recurrence is not failure.

Search the existing SSOT, skills and scripts first. Extend or migrate an existing owner when it fits.
Use a focused skill for contextual judgment, a script for deterministic repeated steps, or a skill
calling a script when both are needed. Keep authority, applicability, inputs/outputs, platform limits,
unknown results, side effects and verification explicit. Do not copy ad-hoc task scripts into the
runtime or add every learned rule to the common prompt. Link focused units from this context tree
and deliver them only through the existing verified selectors.

A judgment improvement records the original decision, evidence available at that time, expected
outcome, observed outcome, failure classification and the revised criterion. Test the criterion on
the retained failure and an applicable successful control; it must not merely lower the acceptance
bar. Unknown causes remain unknown. Similar failures twice require bounded research before another
correction, as AGENTS.md already requires.

Candidate -> specified -> implemented -> independently verified -> activated -> measured is the
promotion path. Two occurrences trigger evaluation and extraction, not unchecked publication.
Reuse the ordinary code review and knowledge-promotion owners. Keep unverified candidates separate
from verified PostgreSQL knowledge. Deduplicate a recurrence family into one bounded improvement
item; this rule grants no recursive self-improvement loop or additional execution authority.

Measure distinct occurrences, verified reuse count, task success denominator, repeated failures,
manual interventions and time/token cost per accepted outcome. Compare equivalent tasks and retain
failed measurements. Neither creating a skill nor a passing synthetic test proves efficiency or
failure-free operation. Review ineffective automations for revision or retirement.


### Conductor decision improvement

Apply judgment improvement to the conductor's prioritization, assignment, clarification, deferral,
retry/stop and acceptance recommendations. Bind a decision ID to the goal and acceptance criteria,
policy/prompt revision, evidence and state snapshot available then, alternatives considered,
selected action, concise evidence-based rationale, uncertainty and expected observable outcome.
Record decision summaries, not private reasoning traces. Attach actual downstream outcome, review,
rework, interventions and time/token usage later; pending or unavailable outcomes remain unknown.

Distinguish a bad decision from implementation failure, infrastructure failure and changed inputs.
A successful task does not by itself prove a good decision, and a failed task does not establish a
bad one. Evaluate unnecessary refusals/deferrals as well as unsafe acceptance. A material incident
may justify immediate investigation; two distinct similar judgment failures trigger the existing
bounded research rule. Do not retry or lower standards to improve the reported success rate.

Improvement candidates must name one failure family and revised criterion. Compare current and
candidate policy against retained failure cases, successful controls and held-out cases, using only
evidence available at the original decision. Replay is an evaluation, not proof that an unchosen
historical action would have succeeded. Preserve evaluator version, denominator and unknown cases.
An independent reviewer assesses the candidate; the proposing conductor cannot certify itself.
After acceptance, use scoped activation, observed outcomes and a previous-version rollback path.
User authority, acceptance requirements and merge/deploy permissions are not self-modifiable.

Keep immutable decision/outcome facts and unverified hypotheses distinct from verified rules;
PostgreSQL promotion follows its existing owner. Prefer a focused decision skill or deterministic
preflight over common-prompt growth. Report accepted-outcome rate, inappropriate acceptance and
unnecessary refusal findings, recurrence, manual intervention and cost per completed objective.
Do not optimize throughput alone or claim failure-free judgment. This procedure is a specification;
a live recorder, evaluator and automatic policy promotion require separate verified implementation.

### Harness-mediated model transfer and token efficiency

User direction, 2026-09-21: turn previously accepted Astra procedures into scoped skills, scripts,
evidence selectors and executable acceptance checks so Sol can perform qualified task families.
Reuse existing context owners and SDD transfer records; INV-MODEL-001 remains authoritative.
Two comparable executions suggest an extraction candidate, not automatic model qualification.

Bind qualification to task family, scope, model, contract, prompt/skill, toolchain and evaluator
versions. Retain accepted Astra baselines and evaluate Sol on separate held-out cases, including
material rejection and unavailable-evidence cases. Independent acceptance must precede activation.
The model's confidence, a matching answer or a narrow successful pilot cannot authorize routing.
Version drift or an out-of-scope task requires renewed qualification or the existing Astra route.
Keep Claude implementation ownership and Codex acceptance authority unchanged.

Extract deterministic work into scripts first. Supply focused context by immutable reference;
avoid repeated full-repository reads and duplicated instructions. Do not truncate required evidence
to meet an efficiency target. Record provider-reported input/output/cache usage separately, with
unknown distinct from zero. Compare total usage per accepted objective, including failed attempts,
reviews, escalation and qualification overhead, alongside critical misses, rework and completion.
Subscription usage is not a fabricated dollar cost, and a smaller model is not proof of fewer tokens.

After scoped qualification, use executable checks and a predeclared independent sampling policy;
do not require a full Astra rerun of every routine Sol result. Novel architecture, materially changed
boundaries and authority decisions still follow their assigned owner. Escalation must preserve
evidence and side-effect ownership rather than blindly rerun an uncertain operation. Activate or
roll back a versioned qualification through the existing review path; never self-certify it.
