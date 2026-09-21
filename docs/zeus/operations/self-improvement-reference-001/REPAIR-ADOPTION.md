# Adopted reference pattern: explicit recoverable-phase routing (2026-09-21 KST)

This is the attribution and the LIMITS of the one reference adaptation delivered in the
`Rejected analysis -> bounded repair -> resumed work` batch. The rule text is INV-AUDIT-REPAIR-001
in `docs/contracts.md`; the operating procedure is in `AUDIT-SERVICE.md`. Nothing here claims an
upstream execution, a completed source analysis or whole-repository adoption.

## What was adapted, from where

Pinned source (`SOURCES.json`): Ouroboros, `https://github.com/Q00/ouroboros.git`,
commit `f0e17b4b42cc06974f2afaf15606250939cd4f87`.

| Source fact (read, not executed) | What Zeus adapted |
|---|---|
| `auto/resume_routing.py` 1-36: named tools map to NAMED recoverable phases; an unknown tool maps to `None` | A refusal is eligible only when a TYPED diagnosis names it; every unknown refusal maps to a fixed ineligible reason, never to a default retry |
| `auto/pipeline.py` 558-666: validate the persisted seed, distinguish recoverable phases from reconcilable checkpoints, persist recovery before continuing | Re-read the task, the partition generation, the immutable artifact and the recorded digest; commit the correction, its assignment and its audit record in ONE transaction before anything is delivered |
| `auto/ralph_resume.py` 1-109: poll a known job, preserve running/blocked/cancelled distinctions, refuse a checkpoint this runtime cannot poll | A live successor stays `admitted`; a failed or unbound one is `reconciliation_required`, never a strike and never a new attempt |
| `tests/unit/auto/test_interview_pipeline.py` 3279-3339: a callback that raises if an existing handle starts a second run | One deterministic lineage identity: a repeated tick, a restart and a concurrent caller all find the same successor instead of creating a second call |

This is a PATTERN adaptation. No upstream code, test, dependency, name, configuration or license
artifact was copied, and no upstream package was installed or executed at any point.

## What was deliberately NOT adopted

- `ralph_resume`'s plugin branch transitions its pipeline to COMPLETE without proving the remote job
  succeeded (LEARNING-RESUME.md). Zeus never translates a transition into acceptance: `repaired`
  requires a corrected subsystem record persisted by the successor's own checkpoint through the
  existing validators, and a checkpoint alone is `deferred`.
- No resume daemon, no phase registry for the whole harness, no global auto-retry, no deadline
  reset, no lease extension and no second recovery engine. Zeus's existing Fleet reservation,
  execution-generation fence, `Workflow` claim policy, `ResearchAudits.checkpoint` and release
  authority are untouched, and `application/execution_recovery.py` remains the owner of explicit
  execution recovery.
- No adoption of upstream's best-effort or fail-open behaviours reviewed in the same tranche
  (Hermes's gate that continues when its approval module cannot be imported, and its best-effort
  ledger): here an unavailable replay, an unreadable artifact or an unknown state is INELIGIBLE.

## Limits of this adoption, stated explicitly

1. ONE diagnosis family is automatically eligible: the demonstrated missing structured test
   disposition (`Missing subsystem trace: tests`) refused by the PURE content decoder. Relationship
   and evidence-claim rejections (`AuditDraftRejected`), every other validator message and every
   execution, ownership, lease, artifact, store or transport failure are out of scope by
   construction. Extending the family means adding a diagnosis with its own replay evidence, not
   loosening the digest comparison.
2. At most ONE successor per (audit, partition, partition generation, original task, execution
   generation, diagnosis). A second refused draft records `research_required` once and closes the
   family; there is no automatic third call.
3. `research_required` is recorded on this owner's own lineage and reported in its CLI, the audit
   service status and the declared observation with the immutable artifact as evidence. It does NOT
   write a `portfolio_investigations` row and does not dispatch research: the kind-aware portfolio
   projection and the research program's candidate synthesis are other owners' code and were out of
   this batch's allowed scope. An owner who wants a research topic raises it through the existing
   program with this lineage as evidence. This is a known partial adoption, not a silent gap.
4. Admission is per audit and per task, disabled by default, and is never enabled by running the
   service. No global setting, operator script, runtime activation or source-audit mutation is part
   of this batch.
5. The owner performs no model call and writes no analysis content. It cannot repair JSON, invent a
   `tests_not_run` fact or judge a draft: it delivers the bounded diagnosis and the existing
   validators decide. A missing prerequisite must come back as an explicit justified not-run fact.
6. Everything recorded here is contract-test evidence over fixtures. No correction has run in
   operation, no upstream repository was executed, and no claim is made that every refusal can be
   repaired.
