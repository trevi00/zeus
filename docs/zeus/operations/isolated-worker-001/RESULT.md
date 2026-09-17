# Isolated worker 001: owner acceptance record

2026-09-17. Issue #127; PR #128. **The bounded actual operating acceptance passed.**
Operation `isolated-worker-127-canary-3` completed at14:50:56 UTC: actual Claude
implementation, separate isolated replay and independent Codex acceptance. Owner
accepts this delivery's fixed matrix. Merge/issue closure follow the final PR CI
gate. Earlier401 attempts remain below as history, not the current blocker.

## Final actual result

- Runtime code69715d5; owner documentation head8a4eba7; unchanged build-004 image.
- Worker task `ac16c8aa-4819-5181-bf03-1c0b929f13b1`; candidate
  `e6e079c4f06f6853356e6cc4b4ddab90559ba76b`, only learning_progress.py changed.
- Model actually executed in the worker container. Worker tests:4 passed.
  Separate credential-free network-none replay ran the fixed four tests twice,
  both4 passed/exit0; inspection31487397b16eebe9365fe04569fa7a68c1451cf06e5a994a69488397a6fc81b3
  reports1/1 checked, no mismatch or replay failure.
- Session `d61eb522-1ff0-40f8-9888-079e109078b3`; actual SessionStart1,
  PostToolUse1 receipts; approved profile digest unchanged.
- Independent lead decision `65620069-2b98-4a2b-8ba7-ccb2b30e6a77`: accepted.
  Owner inspected all11 command events: Git/file/artifact reads and verdict output;
  no candidate execution on host and no fileChange events. This is observed
  behavior, not OS-enforced lead isolation.
- Worker and two verifier run records are removed; owned-container inventory0.
  Observation collection51 inserted, sink failures0, corrupt0, refused0.
  Exact-token hits0 in scanned artifacts; secret was never placed in argv.
- Ledger107->109: exactly one worker and one lead. No automatic retry. Prior two
  authentication attempts and implementation correction rounds remain preserved.

Raw evidence: `canary-3/`, including receipt, records, worker observations,
owner-review-audit, lifecycle records and content-addressed execution/replay
artifacts. The tracked evidence index binds these files. The success is for this
small owner-authored acceptance task, not Code Tutor completion or continuous
unattended production. No additional model call is needed for this delivery.

## Delivery and ownership

The one frame remains [SPEC.md](SPEC.md). Zeus dispatches through Redis and
PostgreSQL, then uses a pinned Linux image and the approved worker-v1 profile
to execute Claude in detached source staging. Evidence replay has a separate
credential-free, network-none container. Codex retains analysis, acceptance and
integration. Unverified work is not promoted into knowledge.

This packages selected approved local-harness adaptations, not all local Claude
assets. The profile document remains
`25b1fe9450cec6000b23f0c03e97085f29c10bf39d579dfe44c4c5314dc10e14`.

## Decisive evidence

Raw root: `D:/workspaces/zeus/artifacts/isolated-worker-001`.
[evidence.json](evidence.json) binds the retained files by hash. Large raw evidence
is local to this machine; a hash is not a remote copy or independent verification.

| Check | Observation | Limit |
|---|---|---|
| Zeus correction-3 worker and independent lead | Accepted candidate 69715d5; lead reports 130 passed, 4 skipped, 1 deselected; 365 synthetic cleanup-proof combinations | Model review plus its retained tool evidence; owner checks below are separate |
| Owner standard focused tests on Windows | 131 passed, 4 skipped | Relevant isolated/evidence/profile/operation/architecture paths, not whole suite |
| Owner focused WSL tests, Docker enabled | 133 passed, 2 skipped | WSL orchestration over Docker Desktop; not native Linux host |
| Owner Windows isolated-worker tests, Docker enabled | 32 passed, 1 skipped | Includes real owned-container stop/removal |
| Actual image build and profile-selected tool checks | Build exit 0; Claude 2.1.274; pytest 9.1.1; ruff 0.16.6 | No model call during build |
| Real child/capture interruption | Stop and propagation in 0.047 seconds; watchdog unused; child gone | Interruption injected; container owner doubled |
| Unconfirmed client cleanup | Retained unresolved record; retirement/reconciliation refused; owner cleaned child | Real child/capture with injected cleanup failure; container operations doubled |
| Post-start Docker interruption | Durable run record; container exited; owner removed exact container | Interruption injected after actual Docker start |
| Actual isolated Claude call | Provider 401; SessionStart receipt 1; PostToolUse 0 | No successful inference or full hook cycle established |
| Secret and cleanup checks after actual call | Exact token hits 0 in scanned artifacts; owned-container inventory empty | Artifact scan limited to files <=64 MiB; no broader secrecy guarantee |

Image:
`sha256:d587a4595e303a0bb5afe430d32d3217fc2f88d0f4047f69c0b72b858fd9c521`.
The source archive and build receipt bind it to runtime 69715d5.
GitHub CI for that runtime is [run 35214818735](https://github.com/trevi00/zeus/actions/runs/35214818735);
its final conclusion must be checked separately, not inferred from local tests.

## First actual attempt and then-remaining gate (historical)

Operation `isolated-worker-127-canary`, task
`a9614e6b-f30c-5984-a0a5-ecfdec2d49c1`, session
`dbc70e05-48c4-42c2-951f-a966ad7e7964`, container run
`90ef9e8d4bdc430a9b145dd6415a9616`.
The owner-authored small acceptance repository was pinned at
`8d02c188199c9b89770b9fdd9770bb0e885bf304`. This was intended as a real model
task over a small test repository, not a Code Tutor product-completion claim.

The token was present, decrypted locally and passed in memory to the Docker
client environment. The server rejected it. DPAPI storage/decryption does not
establish token validity; the cause of the rejection is not established here.
The container started, the approved SessionStart hook ran, and Claude returned
an error before tools or candidate changes. Zeus recorded `execution_retry` and
stopped this operation without retrying. The container was stopped and removed;
the durable record and inner result were preserved. `imported` in that container
record means the unchanged staged file set was processed, not task success.

Machine call ledger: 97 before this delivery, 106 after the failed actual attempt.
Implementation/review rounds consumed eight starts; the actual attempt consumed
one reserved start. One remains under ceiling 107, insufficient for another
worker-and-lead pair. After local credential renewal, record an explicit bounded
budget revision in SPEC before a new operation; never requeue the old attempt.

Remaining acceptance: renew the container credential locally, run one new actual
task with the same fixed four tests, inspect isolated replay and live hook evidence,
obtain independent lead acceptance, confirm cleanup, then accept final CI and
decide merge/closure. Do not reopen accepted environment/cleanup investigations
without a materially changed boundary or failed acceptance check.

## Retained failures and limits

Renewal continuation: operation `isolated-worker-127-canary-2` at owner head
ffa756b also received401, with no candidate or review. The stored value changed,
but lacks the expected OAuth setup-token prefix. A network-none, no-model Docker
probe confirmed the stored bytes reach the container unchanged. This narrows the
remaining gate to credential input/validity; a browser login-code mix-up is only
a hypothesis. The local helper now explains the stages and rejects unexpected
format before storage. Raw evidence is in `canary-2/`; ledger107, automatic retries0,
exact-token artifact hits0, owned-container inventory empty. The revised ceiling108
still cannot fit another worker/lead pair without an explicit frame revision.
CI run35215194425 passed at6b060c2 (before these documentation-only updates).

The first lead timed out; correction-1 and correction-2 leads rejected real cleanup
defects; correction-3 was accepted. The initial image had a CLI target failure;
the next image exposed the profile interpreter resolving outside its environment.
Both were corrected and the actual build checks now pass. A prior full owner suite
had 1914 passed, 448 skipped and one architecture-fixture failure, subsequently
fixed and covered by the standard focused suite. These are not presented as a
clean first attempt. The frame retains the reasons for each bounded correction.

Worker network is bridge, not an egress allowlist; repositories must be trusted
and owner-selected. Lead review remains on the host with instructions not to
execute candidate code; this is not OS-level reviewer isolation. Host project
evidence profiles are refused in this first mode. Continuous unattended operation,
full local-harness absorption and production deployment remain outside this delivery.
