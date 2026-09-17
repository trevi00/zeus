# Isolated Claude worker 001 — one operating delivery

Owner: Codex. Implementation: Claude through Zeus. Frame fixed 2026-09-17.
Baseline: 67a810328799974649d92e99ec0125661c16fd20 (PR126).

## Outcome and completion

Run one real, bounded Claude worker task inside a Linux Docker container, with the existing
approved worker harness, independently replay its evidence in a separate credential-free
container, obtain a Codex lead decision, and preserve evidence before cleanup. Installation,
configuration, a fixture and model self-report alone do not satisfy completion.

The user authorizes design, Claude implementation, actual bounded calls, independent review and
integration. Codex owns this frame and acceptance. Claude may implement the paths in its operation
manifest, supply focused tests and an implementation report; no merge or issue closure by Claude.
Initial ceiling: four new model starts (one implementation/review pair, one canary/review pair),
machine ledger 97 -> 101, no automatic retry. Implementation Claude deadline 1800 seconds and
declared USD8 provider cap; canary 900 seconds/USD4. The USD flag is a declared provider control,
not a measured spend guarantee. Owner may explicitly revise this same frame if a material obstacle
requires another bounded run, recording the reason and consumed calls first.

Not included: full upstream asset absorption, scheduler, parallel teams, network egress allowlist,
native Windows containers, production deployment, automatic restart, knowledge promotion or
changing the global host defaults. No recursive environment investigation. Existing host execution
remains compatible when isolation is not selected. Selecting isolation must never fall back to it.

## Facts, sources and limits

Inspected local source: ClaudeCodeRuntime (claude_cli.py), worker_profile.py and packaged worker-v1,
Executor, bootstrap.build_executor, operation_cli identity/run, EvidenceInspector and source_execution.
Current operation has real Redis/PG reservations, unconfirmed invocation markers, audit/outbox,
budget ledger, independent lead and artifact store. Claude and deterministic replay currently run
on the host. DockerSourceRunner already establishes image-ID, owned-container and source-copy
conventions; reuse suitable helpers/invariants instead of adding a second policy authority.

The worker profile has a 6000-character limit, currently 5998 characters; approved document digest
25b1fe9450cec6000b23f0c03e97085f29c10bf39d579dfe44c4c5314dc10e14.
Its manifest pins the document, standalone hook, narrow Bash grants and selected reference sources.
Do not modify those approved bytes to solve container wiring. These are selected adapted assets,
not proof that the entire local Claude harness has been absorbed.

Primary sources opened 2026-09-17:
- https://code.claude.com/docs/en/devcontainer : Claude can run inside a container; pin CLI release
  and disable updates; host secrets should not be broadly mounted. Container access is not a
  complete security guarantee and outbound access needs separate controls.
- https://code.claude.com/docs/en/authentication : setup-token issues a subscription token suitable
  for CLAUDE_CODE_OAUTH_TOKEN. No API-key billing migration or host credential-directory copy.
- https://docs.docker.com/engine/containers/run/ : explicit mounts, non-root execution, read-only
  root, dropped capabilities, resource and network settings provide distinct controls.
Local observed versions: Claude Code 2.1.274; Docker Engine 29.7.2. Windows host with Docker Desktop
Linux engine; WSL is a second orchestration host, not a claim of native Linux-host validation.

The token is DPAPI-encrypted at the user's existing home secret path and locally decryptable.
Actual container authentication is unverified until the canary. Source tree size is approximately
58 MB / 4975 tracked files. These observations justify bounded staging, not arbitrary repository support.

Inference: reusing the trusted existing Claude runtime inside the image avoids a second stream,
session/model and hook parser. A Docker-client process tree alone cannot own the container.
Unknowns: actual OAuth inference in this image and live hooks under its paths; required canary checks.
Worker bridge networking is explicitly allowed for inference; host-network reachability/credential
exfiltration by hostile code is not eliminated. This release is for trusted, owner-selected repositories.

## Complete path and ownership

Host config selects isolation -> validated immutable image/config identity -> existing operation
reservation -> safe detached source staging -> owned container create/start -> trusted image entrypoint
reuses ClaudeCodeRuntime -> terminal output and actual hook receipts -> confirm container stopped ->
validate/import candidate regular files -> separate container evidence replay -> existing Codex lead
review -> owner acceptance/integration. General events, development commands/results and operational
lifecycle/cleanup failures retain existing task/attempt/session links. PG/Redis and the machine ledger
stay on the host. Provisional results stay provisional; no ontology promotion is added.

### Configuration and trusted runtime

Add an opt-in host configuration (ZEUS_WORKER_ISOLATION=docker and ZEUS_WORKER_IMAGE=sha256:<64hex>,
following existing ZEUS/HARNESS normalization). Absent configuration preserves exact host behavior.
Reject unknown/partial configuration and unavailable Docker/image before provider entry. Record
effective image, limits, harness digests, CLI version and isolation mode in invocation/result evidence;
bind mode/image/limits into operation identity and replay cache identity. Never accept an image,
mount, executable or credential from model output. Refuse host project-evidence profiles in this first
mode unless implemented with complete explicit in-container mapping; do not silently execute on host.

Create Dockerfile.worker with fixed Claude 2.1.274, Python >=3.12, git, locked project dependencies,
pytest and ruff. Trusted installed package at /opt/zeus; candidate at /workspace must not shadow the
entrypoint or pinned hooks. Reuse packaged worker-v1 with its restricted permission surface, hook
receipts and settings-source restrictions. Do not copy ~/.claude, personal agents/commands/MCP or
unreviewed global assets. DISABLE_AUTOUPDATER=1 and disable nonessential traffic. No broad bypass.

Prefer an inner trusted Python entrypoint invoking existing ClaudeCodeRuntime with container-native
paths and sending bounded tagged events/final result over stdio; the outer adapter owns Docker and
forwards on_event/on_tick/cancel/on_enter according to the existing executor contract. Do not misuse
the existing fixture-only launcher parameter to label a real operation as a fixture. Schema, session,
model, budget and terminal checks remain the existing runtime's authority. The outer wrapper must
not report an inner successful result before owned-container termination is confirmed.

### Source, mounts and credentials

Export the pinned candidate into a fresh directory under task runtime on D (or native Linux runtime).
No direct bind of the original checkout or worktree .git indirection. Validate before materializing:
safe relative paths, Windows unsafe names/case collisions, no symlink/hardlink/device entries, <=10000
files, <=256 MiB total, <=16 MiB per file. Unsupported input is explicit refusal. A minimal standalone
git repository can be initialized before worker entry for its read-only git commands; no remotes,
hooks or host .git metadata. Never invoke host git against a worker-controlled staging .git afterward.

Only dedicated staging and evidence directories may be mounted read/write. Root filesystem read-only,
non-root uid, tmpfs home/tmp, --cap-drop ALL, no-new-privileges, finite memory/CPU/pid limits; no Docker
socket, host home or published ports. Validate outputs after stop with equivalent containment/bounds;
import regular additions/edits/deletions to the real candidate only after complete validation, excluding
staged .git and generated caches. Preserve failed staging and a recovery reference; no broad cleanup.

Owner launcher decrypts DPAPI into process memory; runtime accepts only the OAuth environment value
needed for worker authentication. Pass its name, never value, in Docker argv. No image/build-layer,
Git, stdout, debug environment dump or full docker inspect archive may contain the token. No Zeus
database/Redis credentials enter the worker. No token enters the verifier. Docker's administrator can
inspect container environment: this is not protection against a host administrator.

### Lifecycle and verification

Unique UUID name plus ownership label; record exact container id before start. If create response is
lost, only exact name+label may recover ownership; never delete by common prefix. State sequence:
prepared -> created -> start_requested (external-effect boundary) -> running -> stop_confirmed ->
validated/imported -> evidence_retained -> removed. Timeout/cancel/protocol loss uses owned container
kill/inspect plus bounded client-tree cleanup. Unconfirmed stop must flow to existing blocked/unknown
semantics and recovery reference, never a safe retry. Startup must report previous unresolved owned
container state or refuse; no duplicate operation or implicit restart. Evidence must exist outside the
container before removal. Model output is not proof of cleanup, hook invocation or task acceptance.

Add a Docker evidence backend/subclass that retains existing authorization, classification, binding
and archival. Each authorized replay uses a fresh candidate snapshot, same immutable image, no auth,
network none, same resource/filesystem controls. Trusted image Python executes the authorized claim;
do not execute candidate commands on the host. Snapshot identity must describe the container context.
No new command grants. Lead Codex remains host read-only review of diff and preserved observations;
in this mode tell it not to run candidate code, with all executable evidence supplied by the isolated
inspector. This is worker/verifier isolation, not a claim that the lead itself is containerized.

## Fixed acceptance matrix

| Path | Acceptance / decisive evidence |
|---|---|
| Normal | Actual Claude edits a small scoped task in the container; image/profile/hook/session/model bindings recorded; separate replay and Codex review succeed |
| Harness | Approved profile digest unchanged; actual SessionStart and PostToolUse receipts observed; delivery alone is not execution |
| Isolation | Inspect only selected fields for mounts/user/network/caps/limits; sibling sentinel and host secret/config directories not mounted; verifier has no auth or service credentials |
| Failure | Missing image/daemon/token and unsupported source/config refuse; no host fallback or imported partial output |
| Timeout/cancel | Real non-model sleeping process container terminates within timeout plus explicit cleanup window; unconfirmed termination yields blocked/unknown |
| Unknown | Invalid/truncated protocol or missing terminal/hook evidence is reported as missing, never fabricated success; secret values absent from artifacts |
| Concurrency/restart | Distinct owned names, exact recovery identity; one task cannot clean another; retained unresolved run is visible/refused, no auto model retry |
| Source/output | Traversal/link/oversize/collision refusals; no worker .git execution on host; additions/edits/deletions and failed preservation have honest outcomes |
| Replay | Fresh credential-free network-none containers; existing policy rejects unauthorized argv; image/config changes invalidate cache; no candidate command on host |
| Compatibility | Default host mode and existing tests remain valid; Windows owner actual run and WSL focused Docker check; native Windows containers N/A |
| Cleanup | Own stopped containers removed only after preserved evidence; other containers untouched; failed cleanup retains exact recovery reference |

## One delivery batch and evidence

Claude implements Docker runtime/source ownership, inner entrypoint, container replay, fixed worker
image, narrow executor/bootstrap/operation wiring, contract INV-ISOLATED-WORKER-001 and focused
tests. Reuse existing authorities; no parallel scheduler, copied policy engine or unrelated cleanup.
Allowed source modules: adapters/isolated_worker.py, adapters/isolated_worker_entry.py,
adapters/isolated_evidence.py; modify executor.py, evidence_inspection.py (only injection seams if
needed), operation_cli.py and bootstrap.py. Dockerfile.worker and focused tests are included.

Claude runs python -m pytest tests/test_isolated_worker.py tests/test_isolated_evidence.py
tests/test_worker_profile.py tests/test_operation.py -q -p no:cacheprovider and python -m ruff check .
using the delivered interpreter. Tests requiring Docker have an explicit availability marker and
are run by the owner; no provider calls in tests. Fixtures/injected failures are labelled. Owner
runs required full suite and CI, actual bounded container checks and model canary, and reviews the
fixed matrix once as a coherent batch. Material regressions return one consolidated handoff.

Raw evidence: D:/workspaces/zeus/artifacts/isolated-worker-001/<run-id>. Small manifests/results stay
here in Git with run ids, runtime/source/image hashes and command outcomes. No passwords or raw
environment dumps. Report actual failed attempts as well as passes. Nonblocking gaps become explicit
follow-up conditions, not moving acceptance. Completion requires the actual operating loop, owner
acceptance, preserved evidence and clean owned-container inventory; design or implementation alone
is not operation completion.

## Consolidated acceptance correction 1 — 2026-09-17

Candidate bcedb56c3c9e711a1ff13cad50234d37a4b1cd5d. Claude completed implementation;
Zeus replay reported all_checked (3/3). Automated lead invocation hit its 300-second turn limit,
so the operation is failed/execution_blocked, not accepted. Preserve it; do not requeue or clear
its reconciliation record. Codex owner completed the fixed-path review and the decisive checks
below. This is one bounded correction, not an expansion to unrelated environment work.

Accepted evidence retained: ruff passed; actual sleeping-container termination/removal tests passed
on Windows (9.05s) and WSL (2.88s), with no labelled containers remaining. Image build produced
sha256:a51736328f3329aed3589916f71b4b807979821470b3b0e7bf41e295b62b36b4.
Docker build log ends in completed export; PowerShell wrapper returned 1, so that wrapper status is
not represented as exit 0. A corrected build will capture the actual child exit directly.

Three required corrections, same completion conditions:

1. **R1 / normal startup:** Dockerfile links `/usr/local/bin/claude` to missing `cli.js`.
   Real `docker run --entrypoint claude <image> --version` fails. The installed package's bin field
   is `{"claude":"bin/claude.exe"}`; that actual executable reports 2.1.274 in the Linux image.
   Preserve the installer's real executable/link (or derive its package-declared bin), do not assume
   the obsolete path. Build must run `claude --version` and fail if unusable. Owner rebuilds and
   verifies it before any real model call. No dependency/version change is needed.

2. **R2 / required CI:** `uv run pytest -q` fails collection with ModuleNotFoundError: tests,
   in test_isolated_evidence.py's cross-test import. `python -m pytest` inserted the checkout root
   and hid the problem in the submitted check. Correct shared test-fixture imports so both supported
   entry forms collect and run without a new global PYTHONPATH requirement. Preserve coverage.
   Owner verifies the standard uv invocation; worker can use its permitted python -m pytest command.

3. **R3 / cancel, ownership and evidence:** DockerEvidenceInspector._replay creates and starts a
   container without a finally ownership boundary or durable recovery record. Owner's
   artifacts/isolated-worker-001/review-cancel.py injects KeyboardInterrupt immediately AFTER a REAL
   docker start; the exception propagates with that container still running and zero run.json records.
   This is a labelled injected cancellation, not a naturally observed incident. Owner removed its
   exact captured id (exit0); no foreign container was touched.

   Observation -> invalid assumption: the worker has a durable owner, but the verifier assumes
   capture always returns. Both create/start paths must share the same ownership rule, independent
   of how capture exits. Revise the existing ownership implementation coherently: record exact
   run/name/label/id and state durably before start; enclose start/capture in try/finally; cancel,
   timeout, observer failure and unexpected capture exceptions attempt bounded stop/confirmation.
   Unknown stop retains a durable exact recovery reference and cannot be success. Persist bounded
   output/result observations outside the container before remove (also retain the worker's full
   redacted inner result, not only inner_failure/inner_terminal). Cleanup/recovery must cover both
   worker and verifier records, including restart visibility. Never run candidate commands on host.
   Reuse OwnedContainer/run-record helpers; do not add a second scheduler, automatic retry or
   fallback. The cleanup window must bound its Docker calls using remaining time; a 60-second
   inspect must not silently sit outside a declared 30-second cleanup window.

   Regression: owner-injected post-start interruption must terminate/remove or leave a durable
   unknown recovery record, never an unrecorded running container. Add synthetic failure tests for
   unconfirmed stop and evidence-write failure and normal replay, clearly labelled. Preserve the
   already accepted source/permission/profile/default-host behavior. An ordinary successful run
   still requires the owner actual canary, not just these regressions.

Budget revision: observed machine counts 97 -> 99 (implementation and timed-out lead), no actual
container model call yet. One explicitly authorized correction/review pair plus the reserved
container canary/review pair sets the new ceiling to 103 (six total new starts). No automatic retry.
Correction Claude cap USD6 declared, 1200s; review scope is these corrections and directly affected
interactions, preserving the prior fixed frame. Owner tests then decide acceptance; no speculative
review expansion. The canary remains unstarted until these material gates pass.

## Image and capture ownership reframe — 2026-09-17

Candidate fd5dfa6c2b91180206779f7227b69ae01939515a. Preserve correction-1 results: image builds
with exit0 and Claude 2.1.274 starts; the standard pytest entry collects; the owner's injected
post-start REAL container cancellation now leaves no running container and one durable run record.
That probe replaced capture and establishes the outer finally only, not capture's own teardown.
Owner full suite: 1914 passed, 448 skipped, one failure in the architecture test (below), 506.14s.
Independent lead completed and rejected on a material inner-capture cancellation defect. Its
execution is sha256:e3ec378cc6deb0130fb702ea6482968bca448730e4a45f413c9aa4f1cad33364;
raw command/output preserved in correction-1/lead-reproducer.json on D. No actual container model
call yet. This is the same ownership family, so revise the complete teardown sequence, not another
outer exception patch. The fixed acceptance matrix and already accepted source/config/profile
behavior do not expand.

### Remaining image contract

Observation: image a27317b5a25d70841cf50d0934e7c03c64695c568cd7906943c8e24855f47901 starts Claude,
but the real `verified_interpreter`/`profile_environment(child_environment()[0], ...)` selects
`/usr/local/bin/python3.13`: Path.resolve follows the /opt/zeus venv symlink. Under THAT environment,
`python -m pytest --version` and `python -m ruff --version` both exit1 (module missing).
The assumption that an installed venv and a valid binary imply a valid worker environment is false.

Competing solutions: change the shared interpreter helper (broad host behavior change) or construct
the image with a venv-local copied interpreter (local image change). Owner's disposable, network-none,
no-mount experiment replacing that symlink with a copied interpreter selects /opt/zeus/bin/python
and both tools exit0. Choose the image-local solution. Create the venv with `python -m venv --copies`
before uv sync, or an equivalently verified copied interpreter. Do NOT change approved worker profile,
host interpreter policy or permission grants. Add a build check using the ACTUAL profile-derived
environment and Python resolution for both pytest and ruff, not merely `/opt/zeus/bin/python -m`.
Retain the existing Claude version check. Owner's build-image.py captures child exits and repeats
these probes without credentials before canary.

### Remaining capture ownership contract

Lead's reproducer uses the REAL evidence_inspection._capture and a REAL local sleeping Python child,
with just the first process.wait injected to raise KeyboardInterrupt. hold's Owned container is a
test double recording stop time; advance/retire are patched to avoid checkout writes. At 32 seconds
stop was still uncalled and the child alive. A watchdog killed it; only then did pipe.close unblock,
the interruption propagate and hold call stop. This is injected local-child evidence, not Docker.

Invalid assumption: capture returns/raises promptly to its outer owner. In fact _capture catches
TimeoutExpired only, then closes streams in finally while reader threads may still hold read locks.
Required complete sequence: capture/normal wait -> timeout/cancel/exception -> terminate the owned
client process TREE -> bounded drain/join -> close only streams whose readers are finished -> outer
container stop/confirmation -> durable observations/recovery -> removal when safe. Reuse existing
ProcessTree, no second process supervisor. No blocking close while a live reader owns the stream.
If a tree/reader cannot be reclaimed, report that fact and retain ownership/recovery information;
do not turn partial capture into success or silently discard resource debt. Preserve the original
KeyboardInterrupt/exception after bounded cleanup. Container lifecycle must still run if client
capture cleanup fails. Normal output hashes/byte counts/classification and default host replay
authorization must stay compatible. If a minimal shared _capture refactor is necessary it is now
explicitly allowed, with tests of normal, timeout and interrupted paths through the real helper.

Decisive regression: actual sleeping child + first wait interruption (if using ProcessTree, inject
on the real returned process's wait, not on a fake process). A watchdog is only test cleanup, never
the mechanism that makes the test pass. Assert child/tree cleanup and timely interruption/owner
stop BEFORE watchdog. Preserve the real Docker outer-cancellation check; do not replace it with
fixture success. Retest the directly affected stream/cleanup behavior, not unrelated providers.

### Required suite compatibility and next bounded batch

The one full-suite failure is test_architecture::test_tests_assert_behavior_not_source_text:
test_isolated_worker.py's assertion reads a generated temporary `src/pkg/mod.py` fixture, which
the existing heuristic mistakes for production-source inspection. Make the generated fixture path
explicit in the test while preserving the byte-copy behavior assertion. Do not change the architecture
guard, add an exemption, or drop the check. Include tests/test_architecture.py in focused validation.

Claude changes only image construction, capture/lifecycle code and affected tests/report. Owner then
runs fixed gates: standard focused + full/CI, build actual-profile preparation checks, original
real-capture cancellation reproducer and owned Docker cleanup, followed by the reserved actual task.
No source/profile/policy redesign and no new research topic. Counts are 101 after two implementation/
review pairs; one explicit correction/review pair and the reserved actual pair set ceiling 105
(eight starts total from97). Correction cap USD6 declared/1200s. No automatic retry or requeue of
prior failed operations. Native Linux host and restricted network egress remain out of scope.

## Final cleanup proof join — 2026-09-17

Candidate eb822013120f55718578378ef736478fc1051f2a. Preserve these accepted measurements:
build-003 exit0; image b3c0d3b56559522ccc4b7b8b51c676b5abbde503b110049f24a3a2205c93a856;
Claude2.1.274 and actual-profile pytest9.1.1/ruff0.16.6 all exit0; owner real-capture interruption
propagates and calls outer stop in0.047s, watchdog unused, child gone. Standard focused invocation
121 passed/4 skipped; WSL focused including real Docker123 passed/2 skipped. Windows real Docker
termination/removal passed; real-container cancellation leaves no running container and one durable
record. No new review of those accepted paths is requested.

Independent lead found one remaining reachable violation: hold reads cleanup proof from exceptions
but ignores a NORMAL return's `run.cleanup`. With a real child and injected termination failure,
capture returned confirmed=false and child_alive=true, while outer state became removed and
unresolved_runs was empty. The reproducer used mocked container/storage and an actual local child;
its own cleanup subsequently succeeded. This is not a naturally observed OS failure. Nonetheless
an explicit unknown must not become a resolved record. Owner canary is still unstarted.

The assumption to replace: normal Python return is proof that capture resources are gone. It is not.
Use one positive cleanup-proof join for both exception and return outcomes. Reuse `_reclaim`'s
existing confirmed/debt record; do not create another process supervisor or change source/profile.
For verifier captures, make that proof explicit for every return (including clean exit), consume it
in hold/retire, and fail closed if it is absent/malformed. Worker client callbacks remain their
positive proof source. Combine provided proofs; no supplied false/unknown may be overwritten by
another true. Returning a failed capture may be correct; forgetting its live resources is not.

| Container stop C | Capture/client cleanup P | Durable evidence E | Allowed lifecycle result |
|---|---|---|---|
| true | true | true | retire/remove permitted; preserve actual task/replay success or failure separately |
| true | false/unknown/missing | either | stop_unconfirmed; retain exact recovery and cleanup debt; not resolved |
| false/unknown | either | either | stop_unconfirmed; no success/resolved claim |
| true | true | false | retained unresolved evidence state; no cleanup that discards required evidence |

Implement this join once across hold/retire and test the COMPLETE lifecycle with real capture and
real local child: (a) normal exit + confirmed cleanup; (b) returned unconfirmed cleanup; (c) raised
interruption + unconfirmed cleanup; (d) missing proof; (e) evidence write failure. Inject termination
failure at the real helper's cleanup dependency, not by replacing capture with a fabricated success.
Unknown cases must leave recoverable state visible to unresolved_runs and must not call successful
retirement. The same rule covers `reconcile`: container absence alone must not erase recorded
unconfirmed client/capture debt (refuse with that named reason until it is independently resolved;
do not invent an unmeasured recovery). Include this downstream state transition in the regression.
The owner/test finally cleans its own child. Normal and known-failure replay remain
compatible; no host fallback, widened permissions, automatic retry or new feature.

Also correct the documentation estimate: capture teardown may take approximately35s before the
separately bounded container cleanup, not25s. This is a description correction, not a demand to
redesign those already bounded windows. The independent reviewer found ignored bytecode without
an initial inventory; complete checkout preservation was therefore not established for that review.
The files were left untouched; do not erase evidence or retrospectively claim a pristine inventory.

One narrow correction/review pair is authorized on this same frame, ceiling107 (current103 plus
that pair and the reserved actual pair; ten starts from97). Claude cap USD4 declared/900s. Scope:
capture proof propagation, lifecycle join, affected tests and report only. Keep Dockerfile/image
interpreter/profile unchanged. Run focused evidence/isolated/architecture tests and lint; owner/CI
own broader checks. After these decisive checks pass, proceed to the actual operation; no further
exploratory pass absent changed evidence or a material failed acceptance condition.

## Actual acceptance attempt: authentication gate, 2026-09-17

Correction-3 candidate69715d5 was independently accepted. Owner focused checks,
real client cleanup probes and Windows/WSL Docker checks passed; build-004 binds
the image to that candidate. Preserve these results. See RESULT.md and evidence.json.

The actual operation isolated-worker-127-canary reached the container and its
SessionStart hook, then the provider returned 401 Invalid bearer token before tools.
The owner stopped without retry, preserved the inner result, and confirmed owned
container cleanup. Storage and DPAPI decryption were proven; server acceptance was
not. Do not reinterpret this as completed inference, replay or lead acceptance.

User action requested: renew the setup-token credential locally, never in chat.
The old attempt remains stopped and retained. Current machine ledger106/ceiling107
leaves one start, not a worker/lead pair. A new pair requires an explicit bounded
revision here after authentication renewal. No code redesign is inferred from401;
the discriminating check is one new actual operation with a renewed credential.
Until that check and final CI pass, retain draft PR128 and open issue127.

## Renewed credential continuation, 2026-09-17

User reports renewal; filesystem metadata confirms replacement at 14:19:24 UTC
and preservation of the previous encrypted token. No secret value was displayed.
One new operation `isolated-worker-127-canary-2` uses the SAME task, acceptance
tests and build-004 image. Current ledger106; explicit ceiling108 allows one
worker and one lead. No automatic retry and no requeue of the old failed task.
Only documentation changed after runtime69715d5; compare source/Dockerfile/lock
before launch. CI run35215194425 passed on the prior documentation head6b060c2.
Actual token acceptance, replay, hook cycle and lead acceptance remain the
decisive checks. Retain all already accepted implementation/cleanup evidence.

The renewed attempt also returned provider401 before tools. Ledger107; no further
model call. Safe metadata checks found the value changed, is92 ASCII characters,
has no whitespace and lacks the expected OAuth setup-token prefix. A network-none
container comparison confirmed host/container bytes equal without printing either
value or digest. Initial comparison was invalid due to a BOM on PowerShell stdin;
the corrected probe removed that BOM from the comparison input and passed.
The container transport is not the observed mismatch. Browser login-code confusion
is a hypothesis, not proven. Official authentication documentation (opened again
2026-09-17) distinguishes browser login code from subsequent terminal completion.
The owner local auth helper now explains both stages and refuses unexpected token
format before replacing the encrypted file. Format checking is not server validation.
Next required user action is to supply the FINAL terminal setup token locally;
retain both failed operations and do not run a third inference until corrected.
