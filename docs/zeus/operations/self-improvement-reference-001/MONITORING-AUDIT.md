# Monitoring and improvement ownership audit — 2026-09-21

## Frame

Outcome: distinguish working observation from unresolved work and actual improvement execution.
Scope: live local status API, Fleet receipts, independent review artifact and projection/UI source.
Read-only inspection; no task retry, deployment, cancellation or acceptance changes. Complete when
source availability, project coverage, current failures and investigation-to-execution ownership
are checked. Visual browser rendering and full historical failure diagnosis are outside this audit.

Path: PG/runtime observations -> monitoring projection -> local API -> React views; Fleet terminal
outcomes -> portfolio failure candidates -> explicit owner disposition/assignment -> actual worker.
Source-read success is not service health; candidate creation is not worker dispatch. Accepted code
is not a deployed release. Preserve these ownership boundaries.

| Check | Observed result |
| --- | --- |
| Source availability | Seven sources report ok; fresh API observations at approximately 12:01 UTC. |
| Operational health | operating_status unknown, health_age_seconds null. A successful DB read does not establish fresh health. |
| Current tasks | Primary projection: succeeded 276, cancelled 17, running 1, expired 1. Lane tasks are separate. |
| Fleet transition | decision-feedback rejected at 11:58:05 UTC; ontology moved from queued/path_conflict to dispatching. |
| Failure evidence | Decision-feedback 2 calls settled, 243 observation records inserted, sink failures/corrupt/refused all 0. |
| Project coverage | 49 unbound jobs; the three project cards are not a complete view of all Fleet work. |
| Repeated failures | Three research_required families, one deferred; grouping by reason is triage, not root-cause proof. |
| Progress investigations | Two low_semantic_yield candidates remain research_required. |
| Repair execution | Harness lane has no successor repair for rejected decision-feedback; candidate queues do not prove a repair team is working. |
| Log freshness | Last collection about 150 seconds old in the sample; quarantine 0. No completeness/SLO conclusion. |
| Unconfirmed ownership | One pending/unconfirmed marker exists; may belong to active work, not proven abandoned by this audit. |
| Restart/concurrency | No fault injection or restart in read-only audit; existing receipts only. |
| Platform/cleanup | Windows local read; no changes to processes, containers, source rows or retained evidence. |

## Material findings and next bounded delivery

All three portfolio projects report needs_attention, no running or queued bound job, and respectively
1/2/1 unresolved failures. This does not mean the whole Zeus service has stopped: an independent
audit task and the ontology Fleet operation are active. Frontend projects.tsx explicitly warns about
unbound jobs; fleet.tsx distinguishes dispatching from a proved running process. These are useful
truthful distinctions, but users must combine several views to determine ownership and next action.

Decision-feedback was implemented and independently reviewed, then rejected. Review artifact:
sha256:048c0a1e19aac8b429706dee6f19b01b994327a92efa04349433be226ebaeeba
Candidate fbfcf1df249fbf130123672e09357221947428a7. Reviewer reports three static traces: repeated
overflow counting beyond 50 retained runs, stale concurrent pending/terminal observations causing
false conflicts, and reference equality without artifact-content verification. No reviewer-side
reproducer ran. Owner must validate these together against the existing frame before one Claude
correction handoff. They are not independently reproduced defects in this audit.

The portfolio application explicitly creates advisory candidates without dispatch. Therefore the
present system supports detection and recorded triage, but this evidence does not establish an
autonomous detect -> diagnose -> repair -> independent review -> release loop. The dedicated recent
improvement job is now rejected and stopped; do not describe it as ongoing repair.

Next batch: validate and consolidate the existing decision-feedback rejection; bind relevant work
and explicit historical-successor evidence to project criteria; specify a single accountable
investigation-to-repair transition using existing Fleet ownership, preserving two-strike research,
idempotency, no self-acceptance and no blind retries. Fresh health production and unconfirmed marker
ownership need targeted checks before any health repair claim. Do not globally mark historical red
jobs resolved or launch one repair per coarse failure family.

PR176 remains independently accepted and CI-passed, not deployed. Ontology started after the prior
task completed, so the previously discussed idle deployment window was not held. Future deployment
must explicitly stop new assignment before draining active work; waiting alone does not reserve it.

Evidence: http://127.0.0.1:8788/api/status; local
D:/workspaces/zeus/artifacts/f2h/fleet/self-improvement-reference-001-decision-feedback/stdout.log;
application/monitoring.py, application/portfolio.py, frontend/monitor/src/views/{overview,fleet,projects}.tsx.
No external research needed: questions concern observed local behavior and explicit local contracts.
