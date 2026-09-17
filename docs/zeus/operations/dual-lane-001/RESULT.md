# Concurrent product and harness work — owner result

2026-09-17. Tracking issue124. Two real Claude workers ran concurrently under pinned Zeus
16de5b0, separate checkouts, PostgreSQL schemas, Redis namespaces and artifact directories.
No live runtime/profile replacement occurred. Raw root D:/workspaces/zeus/artifacts/dual-lane-001.

## Actual operation outcomes

| Lane | Start/end UTC | Result | Calls |
| --- | --- | --- | --- |
| Product | 07:34:56–07:39:41 | accepted; actual independent Codex reviewer accepted717ba83 | 2 settled |
| Harness | 07:35:06–07:43:17 | failed/evidence_gate_refused; no automated reviewer executed | 1 settled |

Operation intervals overlapped about275 seconds. Owner separately observed both actual worker
tasks running together. Machine ledger88->91, ceiling92; no automatic retry and no new call.
Product receipt's global before/after includes the concurrent harness call: its own slots are
the authority for its two calls, not subtraction of those snapshots. One lane's gate failure
did not prevent the other lane's acceptance.

## Product accepted

Existing Code Tutor submissions UI now shows current problem titles. Claude changed the DTO,
service and tests; no new endpoint/migration/frontend runtime behavior. Current titles, null
when missing, per-request distinct-ID lookups, preserved user-scoped ordering/pass counts.
Independent reviewer86 tests; owner133 regression tests; actual browser/API/PG/Redis/Docker
4 scenarios passed in26.0s with retries0 (signup/login, wrong2/3, correct3/3, own history titles,
accountB access refusal). Owner visually inspected accepted-history screenshot. Build passed.
Owner applied Ruff-only test import/UTC-alias normalization after the first lint failure;
13 affected tests and lint then passed. Product code and browser scenario bytes were unchanged.
Final local product revision a2692b6; its TITLES-RESULT.md records details and limits.

Owner build/browser wrappers failed while printing Unicode to cp949 AFTER successful child
exit0. Child logs, passing scenario receipts and wrapper failures are retained separately.
This is not recorded as a successful wrapper. Own app processes/browser stopped, own two app
containers stopped/retained with data. Existing Zeus/flexday services stayed running.

## Harness asset accepted with operator-assisted packaging

Claude candidate e773f4e rewrites selected Baldrix receiving-code-review principles in the
existing worker-v1 profile: verify reviewer claims against actual code/evidence, handle a
complete batch, explain disagreements, fix material findings coherently and keep minor work
as follow-ups. Owner independently compared all old/new requirements and source provenance.
No prior verification, investigation, project-command, structured-report or authority rule
was removed. Unconditional stops, per-item patch loops, style bans and catchphrase were not
adopted; no upstream executable/text or unverified performance/license claim was imported.

The worker could not calculate its manifest digest under its tool policy and honestly reported
incomplete. The stale digest caused8 failed/11 passed profile tests; replay correctly refused.
Owner packaging repair removed eight blank-line separators, words unchanged,6007->5999 chars,
and updated SHA256 to2cbf9684d9214cd2871a3f6d586b72531b676e0671f3f743ab8d63761ba30c5d.
Source bytes match the pinned manifest; prior sources, hook bytes/digest, permissions, id,
version and limit are unchanged. ADOPTION.md describes the worker's earlier incomplete state;
this owner result records subsequent packaging, not a rewritten successful worker receipt.
Existing focused profile tests/lint and full owner/CI checks are acceptance gates; final check
results are linked in the PR record. No model compliance/effectiveness claim follows from text.

## Remaining conditions

Two fully accepted autonomous operation receipts were NOT achieved: issue124 stays open for
the documented worker metadata tooling residual. No blanket shell permission or new runtime
feature was added. A later bounded task can supply the missing supported capability and prove
it in a real run. Three model calls were enough to deliver product improvement plus the
operator-assisted adoption; the spare slot was not consumed for ceremonial repetition.

This proves overlapping bounded operations, not a continuously scheduled multi-team service,
automatic merger/deployer or ontology promotion. No broader issue closes. Code Tutor remains
local: inherited auto-publishing CD needs a separate setup batch before GitHub initialization.
Human/Samsung/product deployment/AI acceptance, whole-reference absorption and model-tier
qualification remain their existing separate goals. All dirty global analysis files are preserved.
