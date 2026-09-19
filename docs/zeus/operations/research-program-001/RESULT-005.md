# Delivery011/012 and live005: early refusal observed, full cycle not accepted

2026-09-19. Integrated runtime31b1b0c4f34ab4f3dd9c4c0df692e6ec3967b8f9.
Claude candidate d2f4d61e44a145761916e0048db5fe1bb1e95a6d has the identical source tree.

```mermaid
flowchart LR
  R[Research succeeded] --> D[DBA succeeded]
  D --> P[Research lead succeeded]
  P --> G[Proposal 4260 bytes exceeds fixed 4096 cap]
  G --> S[Stop before improvement lead]
  S -. not started .-> N[Conductor / implementation / review / tick2]
```

## Completed implementation evidence

- Local byte policy with canonical JSON measurement, producer gates, whole-envelope preflight, role/action
  binding, preserved originals and additive byte telemetry. Legacy non-council input budget unchanged.
- Claude011 timed out before terminal answer; seven changed files were preserved with hashes, then committed
  as7bdbd54. Owner75focused tests passed/3fixture errors; actual raw input replay4/4 passed. Owner consolidated
  three corrections: maximum-input fixture registration, unregistered start-event attributes, and real
  role_retry/whole-window typed error handling. Not a successful worker operation.
- Claude012 completed those corrections. Its first preflight refused base_revision_missing without a model
  reservation; after fetching the preserved local commit the operation ran. Failures retained, not erased.
- Actual Zeus independent Codex review accepted operation research-program-012-input-completion. This reviews
  the completion delta from18e28d6; owner reviewed the complete accumulated change. Do not describe it as an
  automated full original-implementation review.
- Owner85focused tests passed, lint passed, full suite2226passed/455skipped. Skips are not executed tests;
  actual CI supplied Windows3.12/3.14, Linux3.12/3.14 and integration verification. CI gate at31b1b0c passed
  without owner rerun. New image26ec416526347bd3a0ad402df8db11c7af20e8109e86c5ac755117bdea401daf built from
  candidate; installed-policy check passed without network, credentials or model.
- Retained run003/004 input replay:16037,19339,20818,23122 required bytes, each within40960 and raw unchanged.
  Injected store/Git and no-model runtime: delivery evidence only, not semantic comprehension or live acceptance.

## Actual live005

Research, DBA and research lead each succeeded with real executions. Before any improvement-lead call,
producer gate returned needs_scope_split:research_proposal:4260/4096. Run failed; program blocked and paused.
Three slots reserved/settled202->205. No conductor, Claude candidate, independent review or tick2 in THIS run.
The accepted012 operation above is separate. No auto retry/merge/deploy. Fleet paused/active0; only existing
service containers remain. Saved-token artifact scan0hits/0unreadable (not a general privacy guarantee).

## Owner design finding, not a request for another arbitrary increase

Fixed independent caps reject usable shared capacity. The exact current canonical payloads are packet11965,
DBA1677, research proposal4260. Even reserving the entire future improvement allocation8192 and both overhead
allowances8192 gives34286/40960, leaving6674bytes. This offline arithmetic is not a changed runtime policy or
proof the remaining roles would succeed. The old gate correctly enforced the owner specification, but that
specification is too restrictive for this actual proposal. Claude is not being asked to drop content to fit.

Next design in the SAME SPEC frame: retain total40960 and future reservations, evaluate committed cumulative
payload plus future reservations at producer boundaries, so unused earlier capacity can fund a later proposal.
No164-byte tweak, no further live attempt in005, no blanket unbounded output or changed token claims. Exact
implementation/review is pending; full cycle + second collection/stop remains unaccepted. Local absorption
and project observability remain queued operational projects, not additional launch prerequisites.

Raw evidence on D is bound by EVIDENCE-005.json. Failed PG records and preflight/timeout history remain intact.
