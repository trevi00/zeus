# Sterk monitor adoption 001 — owner result

Runtime/UI candidate: `35f7123cc6aa184e7a738cb50f80da345813827c`. 2026-09-18 KST.
Adapted selected freshness and refresh patterns from #75 #76 #99 #100 into the existing monitor.
The catalogue and disposition table are in SPEC.md; this is not all-reference absorption.

## Accepted behavior

- Every source and collector exposes time/age, stale, unavailable and invalid-time states.
- Stale DB observations stop claiming a current running count/agent state; history remains available.
- Healthy Docker/Redis remain visible during database collection failure.
- Partial-page refresh is single-flight, has a 10s abort timer, and preserves search/tab/detail.
- Hidden tabs stop automatic polling; returning to the tab refreshes.
- HTTP outcome remains separate from source freshness. Last successful response time survives
  failure and is updated on recovery. Execution success is not labelled independent acceptance.

No change to PostgreSQL/Git authority, verification gates, runtime scheduling, dependencies or
permissions. No Sterk source code/assets copied, no requests to the reference service this round.

## Verification

Actual Zeus runs: isolated Claude implementation plus independent Codex review, followed by one
explicit correction pair for receipt timestamp formatting. Four calls total, ledger 123 -> 127;
all four settled, no automatic retry, exact-token artifact hits 0. The first rejected receipt is
preserved; the second operation is accepted. Both runs collected observations without sink failure.

Worker/replayed checks and final Windows owner checks: monitoring 7 passed, ruff passed.
Chromium 153 through agent-browser 0.38.1 and a real local HTTP server:

| Check | Result |
|---|---|
| Fresh/stale/future/invalid timestamps | Passed, stale running count becomes unknown |
| DB unavailable, Docker/Redis available | Passed, independent rows stay visible |
| Search/tab/open detail after automatic refresh | Passed |
| HTTP failure, persistence and recovery | Passed, retained history stays accessible |
| Eight joined refresh callers + delayed response | Passed, ~9.5s remaining shared timeout; next refresh recovers |
| Real hidden tab for 7s / return-visible | 0 hidden requests / 1 resume request |
| No new response for >20s | Live count becomes unknown; failure badge and history retained |
| Receipt time success -> failure -> recovery | Passed on corrected candidate |
| Browser console errors | None recorded by agent-browser errors |

The browser input and delayed HTTP responses were controlled fault injection, not measured
operational workloads. Original code showed stale `running=1` and hid healthy Docker on DB failure.
Owner driver initially failed printing Unicode under cp949; that artifact is retained, followed
by a UTF-8 run. No product behavior was changed to accommodate the driver.

## Remaining limits and completion record

Full Windows/Linux/integration CI is the final merge gate; its result is recorded on the PR.
The configured runtime has no monitoring.json, so no live operational snapshot view or production
improvement rate is claimed. This change supplies the monitor, not a new collector deployment.
Samsung/human acceptance, writable controls, complete reference import and continuous autonomy
are outside scope. The isolated worker image/profile are unchanged.

Raw local evidence is on D with hashes in evidence-summary.json; another machine needs those
files transferred to inspect the raw evidence. Refs #74 #75 #76 #99 #100. Closes only implementation
issue #134 after the owner confirms CI; catalogue issues retain their remaining proposals.
