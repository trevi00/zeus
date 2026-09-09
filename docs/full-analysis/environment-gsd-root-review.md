# Environment, fixtures and GSD checkpoint

Starting Zeus revision: 5acaeced22de71ae3eb8584643e00557762745c0.
New primary records: 108 files / 651,451 bytes. Supporting records: 95, excluded
from the new-primary denominator. The prior-unreviewed rows are preserved separately.
The identity verifier checked raw blobs, byte lengths, hashes, declared read ranges
and 374 review references. Record integrity is not proof of semantic correctness.

| Scope | Primary files | Bytes | Supporting files | Evidence |
|---|---:|---:|---:|---|
| Harness environment and fixtures | 16 | 49,545 | 15 | [Joint resolution](harness-environment-fixtures-001/resolution.md) |
| Baldrix GSD references | 32 | 178,518 | 20 | [Independent review](baldrix-gsd-references-001/review.md) |
| Baldrix GSD templates | 43 | 226,301 | 27 | [Independent review](baldrix-gsd-templates-001/review.md) |
| Baldrix GSD workflows | 17 | 197,087 | 33 | [Independent review](baldrix-gsd-workflows-001/review.md) |

Root independently read the 16 primary environment/fixture bodies before viewing actual
Claude's independent review. A second actual Claude discussion compared the original
reports, direct support reads and recorded observation; corrections remain additive.
Those two Claude calls covered the root scope, not the 92 delegated GSD documents.
Root read the delegated review reports and reconciled their findings; this does not
claim a second full independent reading of every delegated source body.

Nine original isolation scenarios and seven original golden.run calls ran in an offline,
immutable Linux container, with five real child commands on scratch fixtures. A newly
assigned state override survives the no-prior-value real_state branch. Equal errors and
same-size/same-mtime rewrites can appear stable. Missing or invalid-but-parseable golden
definitions yield zero cases without failures; duplicate names count twice; stderr can
satisfy expected text; invalid expected exit validation occurs after command side effects.
Controls verified prior-value restoration, changed-input reporting and expected nonzero
exit handling. No source suite, original nine-case golden set, curator/gatewriter/ledger
mutation, fleet service, real PG or human acceptance ran. No full promotion bypass is claimed.

The GSD static reviews found contracts that must be reconciled before adaptation:

- UAT [pending] and human-check headings differ from selected parser formats. Skipped or
  unparsed items cannot silently disappear from the acceptance denominator.
- CLI scaffolds and Markdown templates have different default required fields. SUMMARY
  presence, limited Self-Check and plan counts do not establish requirement acceptance.
- Phase completion treats selected gaps and human-needed warnings as nonblocking. Automatic
  human verification and inferred locked decisions do not represent actual user approval.
- The planning lock has stale-file removal and timeout fallback without demonstrated owner
  fencing. This is static evidence; no crash or race experiment was performed.
- Model profile aliases, context setting names and subrepo refresh semantics differ across
  documentation and consumers. Role names and flags do not qualify Astra/Sol/Terra behavior.
- Archive naming/order, review-result environment names and final repair iteration checks
  have mismatches. Actual preservation, Git state and deployment remain unverified.

Preserve useful source defenses and assets: explicit unknown/blocked/partial states,
user response and deferred-decision records, requirement IDs, UI interaction/copy fields,
read-first and acceptance criteria, bounded repair loops, dirty-tree refusal, real exclusive
lock creation and debugger human confirmation. Template placeholders are valid drafts;
they become dangerous only when consumers misinterpret them as completed evidence.

Source PG is a disposable projection while Zeus PG owns runtime records. Source volume
regeneration assumptions therefore do not transfer. Read-only source mounts, shared writable
state, install reproducibility and component heartbeat scope need actual platform/service
qualification. Existing mount and import-text checks alone do not prove that qualification.

These are advisory additions to existing lock, human verdict, spec/UI, completion, model,
environment, isolation and denominator topics. No new topic is needed merely to duplicate
them. Analysis, an unchanged incumbent test suite and green CI do not resolve these issues.

Coverage now has 1,745 paths with records and 991 unreviewed out of 2,736 tracked paths.
Recorded dispositions still include body-only/static review with call/test trace pending.
Extra local assets are a separate denominator. Full analysis, transitive/license closure,
actual Claude review of remaining scopes, Windows/Linux/WSL qualification, model competence
transfer, real E2E/human acceptance and adoption remain incomplete. Samsung device work is
deferred. No operating harness or deployment was replaced.

The starting revision's CI run 34346165204 completed all five jobs successfully, with raw
response in docs/zeus/ci/34346165204.json. This does not validate subsequent changes or the
upstream findings. Local checks are recorded separately. Issues remain open until implemented
correction, exact-revision acceptance evidence and required human approval are present.
