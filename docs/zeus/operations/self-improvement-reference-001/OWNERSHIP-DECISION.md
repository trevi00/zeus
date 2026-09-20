# Cancellation and resource ownership: bounded adoption decision

Decision: reuse Zeus's existing process/container ownership. Do not import a second
termination implementation or copy Ouroboros's timeout constants. This closes this
specific comparison, not the 95-path provider family or the overall source audit.

## Source and complete affected path

Ouroboros pin: `f0e17b4b42cc06974f2afaf15606250939cd4f87`.
`src/ouroboros/providers/claude_code_adapter.py:118-134` kills the direct child,
waits up to five seconds and logs a warning if it cannot reap it. Lines 715-780
validate encoding before spawn, launch with an explicit child environment and
call that helper on timeout or BaseException while communicating. Its inspected
path does not provide Zeus's process-tree/container cleanup receipt. This is a
source comparison, not a reproduced upstream process leak; upstream was not run.

Zeus baseline: `1382f734352c22282844a18fbe9c2e9fcb57afa7`.
`adapters/isolated_worker.py` records start ownership before the body, bounds stop,
joins container and client cleanup proof, retains unknown cleanup debt, and writes
evidence before removing the exact stopped container. `adapters/process_tree.py`
separately confirms parent exit and Windows Job Object / POSIX process-group state.
The existing unresolved-run path refuses another launch until reconciliation.
These owners already implement the relevant responsibility; an imported direct-child
helper would create a second, narrower authority rather than improve that contract.

## Acceptance and actual verification

Executed trusted local `pytest tests/test_isolated_worker.py -q -p no:cacheprovider`
on Windows with provider credentials and ZEUS/HARNESS settings removed; explicitly
enabled the existing real-Docker test with the already-present immutable worker image.
Result: **32 passed, 1 skipped**, exit 0, 20.085 seconds including runner overhead.

| Condition | Evidence | Limit |
|---|---|---|
| Normal result/import and evidence ordering | Existing fixture checks passed | Fake Docker + local child protocol, not a model |
| Deadline, uncertain stop, refusal of successor | Existing fixture checks passed | Injected Docker state/kill behavior |
| Actual container stop/confirmation/removal | `test_real_sleeping_container_is_killed_confirmed_and_removed`, passed, 1.307 s | Credential-free sleeping container, no Claude invocation |
| Cleanup inventory | No containers returned for the pinned worker image after the run | Point-in-time observation |
| Output symlink rejection | One test skipped: host cannot create symlink fixture | No new proof of that path |
| Cross-platform behavior | POSIX source inspected | No new Linux/WSL execution |

Evidence root: `D:/workspaces/zeus/artifacts/self-improvement-reference-001`.
Receipt `ownership-001.json`, JUnit `ownership-001.xml`, log `ownership-001.log`.
Log SHA-256: `ef7b72c431a61874e9a43c6afb9ba20b9b379841d2915799a59b95e35fe670ac`.
Review is this Codex session's source/caller/owner/evidence cross-check, not a second
independent agent. No runtime implementation changed and no model was called.

## Continuation ownership correction

The read-only Fleet snapshot has no active lane job; the legacy audit lifecycle has
zero registered audits/partitions and no verified active release. Its source runner's
artifact storage must also be reconciled with the D-drive convention before registration.
The reference analysis is therefore interactive, not an active unattended assignment.
No registration, deployment approval or completed checkpoint was fabricated.

Applied workflow improvement: record the decision and relevant check together before
calling a bounded comparison accepted. Distinguish effort, accepted decisions and
actual running assignments. The next source-analysis scope is the remaining provider
adapter/SDK integration and its tests, followed by the existing capability-board order.
Automatic continuation remains unverified; enabling it needs one consolidated integration
handoff covering durable admission, readable artifacts, authorized Codex routing,
checkpoint/restart, activation and visible owner state. It is not a new scheduler.
