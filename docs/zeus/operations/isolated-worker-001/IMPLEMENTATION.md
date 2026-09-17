# Isolated Claude worker 001 — implementation report

Frame: SPEC.md (unchanged). Contract: INV-ISOLATED-WORKER-001 in docs/contracts.md.
Disposition: reuse. `ClaudeCodeRuntime`, the worker-v1 profile, `EvidenceInspector`, `ProcessTree`,
the executor's transport contract and the DockerSourceRunner conventions (immutable image id,
uniquely named owned container, validated source copy) are reused; no second stream parser, policy
engine or scheduler exists. worker-profile-v1 bytes are untouched.

## Interfaces

- `adapters/isolated_worker.py`
  - `load_isolation(settings)` -> None | config `{mode,image,limits,driver_sha256,protocol,network,digest}`;
    `IsolationError.reason_code`: `isolation_config_invalid`, `docker_unavailable`,
    `worker_image_unavailable`, `worker_token_missing`, `isolation_refuses_project_evidence_profile`,
    `isolation_unresolved_run`, `source_*`, `output_*`, `import_*`, `container_*`, `protocol_result_missing`.
  - `preflight(config, docker, environment, token=True)`: daemon, exact image id, token presence (name only).
  - `stage_source`, `init_standalone_git`, `scan_tree`, `plan_import`, `apply_import`: source/output ownership.
  - `OwnedContainer`: `create` (exact name+label recovery), `verify` (selected inspect fields, never
    `.Config.Env`), `state`, `stop` (kill + confirm by exact id), `remove` (exact id, not forced).
  - `IsolatedClaudeRuntime`: the executor transport contract (`enters_on_open=False`, `run(... on_event,
    on_tick, cancel, on_enter, session_id)`); `on_enter` fires at `start_requested`.
  - `IsolatedWorker(config, root)`: `.runtime(...)`, `.inspector(artifacts)`; roots
    `<runtime>/isolated-worker/runs/<run_id>/{workspace,evidence,run.json}` and `.../replays/<run_id>`.
  - `python -m codex_harness.adapters.isolated_worker status <runs-dir>` / `reconcile <run-dir>`.
- `adapters/isolated_worker_entry.py`: `/opt/zeus/bin/python -I -m ...`; stdin one JSON request; stdout
  tagged lines `{"protocol":"zeus-isolated-worker-v1","kind":entered|event|result|refused}`. The result
  line omits `events`; the host rebuilds them from the forwarded event lines.
- `adapters/isolated_evidence.py`: `DockerEvidenceInspector(EvidenceInspector)` overriding only the
  three seams added to `evidence_inspection.py` (`_trusted`, `_python`, `_replay`) and `snapshot`.
- `executor.py`: `Executor(..., isolation=None)`; refuses isolation + evidence profile; isolated
  `_open_runtime`, inspector, `request["isolation"]`, lead `review_context` that forbids running candidate code.
- `bootstrap.py`: `host_isolation(profile)`; `build_executor(..., isolation=HOST_PROFILE)`.
- `operation_cli.py`: `identity(..., isolation=None)` adds an `isolation` key only when selected;
  `run` validates isolation before goal binding, reservation and executor.

## State transitions and failure flow

prepared -> created -> start_requested -> running -> stop_confirmed -> validated -> imported ->
evidence_retained -> removed. Other terminal record states: `refused` (before start, resolved),
`stop_unconfirmed`, or a record left at `running`/`evidence_retained` (unresolved). Any unresolved
record of the same workspace (or an unreadable record) refuses the next run with
`isolation_unresolved_run` before `on_enter`. After `start_requested` every failure raises a
`ContractError`, so the executor's existing `terminated(...)`/blocked path applies; nothing retries.
Protocol loss, inner refusal, refused output or failed import: container still stopped and removed,
nothing imported, staging preserved, record names it. Successful runs delete only their own staging.

## Evidence fields

`result["isolation"]`: mode, image, limits, driver_sha256, digest, run_id, `container{id,name,controls
(image,user,network,read_only,cap_drop,security_opt,memory,nano_cpus,pids_limit,privileged,ports,
mounts[Type,Source,Destination,RW],labels),stop}`, `source{revision,files,bytes,manifest_sha256}`,
`staging_git`, `preflight`, `credential{name,transport}`, `cli_version` (inner runtime's probe),
`harness{profile_digest,host_observed_hook_receipts}`, `stream{reason,violation,lines,stderr_tail}`,
`import{added,modified,deleted,after_sha256}`, `outcome`, `cleanup{removed,recovery}`. The inner
result keeps its own `command`, `session`, `model_agreement`, `worker_profile` (in-container receipts).
Replay runs add `container{name,id,image,network:none,credentials:none,controls,stop,cleanup,snapshot_sha256}`.

## Owner validation commands

1. `docker build -f Dockerfile.worker -t zeus-worker:001 .` then `docker image inspect --format "{{.Id}}" zeus-worker:001`.
2. `docker run --rm --entrypoint claude <id> --version` (expect 2.1.274) and `--entrypoint /opt/zeus/bin/python <id> -m pytest --version`.
3. Set `ZEUS_WORKER_ISOLATION=docker`, `ZEUS_WORKER_IMAGE=<id>`; launcher exports `CLAUDE_CODE_OAUTH_TOKEN` in process memory only.
4. Docker-marked test: `ZEUS_TEST_WORKER_IMAGE=<id> python -m pytest tests/test_isolated_worker.py -q -p no:cacheprovider -k real_sleeping` (Windows and WSL).
5. Canary: `zeus operate run <manifest>`; then `python -m codex_harness.adapters.isolated_worker status <runtime>/isolated-worker/runs <runtime>/isolated-worker/replays` must print `[]`
   and `docker ps -a --filter label=zeus.isolated.run` must be empty.

## Observed by this worker, and not

- Observed: the two commands in the structured answer (results in its summary). All container
  behaviour in those tests is an INJECTED fake Docker client plus a real local child process; the
  timeout test kills a real sleeping non-model process, not a container.
- Not run here (owner-only): image build, any real `docker` command, the Docker-marked test (skipped),
  OAuth inference in the image, live SessionStart/PostToolUse receipts, full suite, CI. Dockerfile.worker is unbuilt.
- Known limits: (1) on a POSIX host running as root the container user is 10001 and a bind-mounted
  staging may not be writable; non-root POSIX hosts use their own uid. (2) `uv run ...` replay claims
  need network/sync and will fail honestly under network none; `python -m pytest|ruff` are the supported forms.
  (3) Superseded by correction 1 below: an observer failure now ends in `removed` or `stop_unconfirmed`. (4) Hook receipts missing is
  reported (`observed:false`), not turned into a failure, matching the host runtime. (5) Bind sources
  containing a comma are unsupported by `--mount` syntax. (6) Worker egress is unrestricted bridge networking (SPEC).

## Consolidated acceptance correction 1 (SPEC final section)

Disposition: improve the existing ownership implementation; no second scheduler, retry or fallback.
Files: `Dockerfile.worker`, `adapters/isolated_worker.py`, `adapters/isolated_evidence.py`, the two
isolated test files, `docs/contracts.md`, this report. Profile bytes, executor, bootstrap,
operation_cli and default host mode are untouched.

- **R1.** The obsolete `cli.js` link is gone. The build derives the link target from the installed
  package's own `package.json` `bin.claude` (owner-measured: `bin/claude.exe`), then runs
  `claude --version` and requires `2.1.274`, once as root and once as uid 10001 through PATH; an
  unusable CLI fails the build. No dependency or version change. NOT built or run by this worker.
- **R2.** `tests/test_isolated_evidence.py` imports its shared fixtures as
  `from test_isolated_worker import ...`, the repository's existing convention (e.g.
  `test_autonomous.py` -> `test_operation`), which relies on pytest's rootdir/`tests` insertion and
  not on the checkout root being on `sys.path`. No PYTHONPATH, conftest or packaging change.
  `uv run pytest -q` itself was NOT run by this worker (not a permitted command); owner verifies.
- **R3.** One rule for both roles in `isolated_worker.py`: `new_record`/`advance` (durable `run.json`,
  a failed write is `evidence_write_failed`), `hold(container, record, body, client=)` and
  `retire(container, record, result, outcome, files=)`.
  - `hold` writes `start_requested` with `{container,name,record}` (record also carries `run_id`,
    `label`, `container_name`, `container`) BEFORE `body` starts anything; a failed write removes the
    never-started container and refuses. `body` (worker: `on_enter` + `_converse`; verifier:
    `_capture` of `docker start --attach`) runs in try/finally: return, cancel, deadline, observer
    failure, KeyboardInterrupt and any other exception all get `OwnedContainer.stop(cleanup_seconds)`
    plus, for the worker, the client-tree termination. Confirmed -> `stop_confirmed` (on an exception
    also `retire(..., "interrupted")`, i.e. record then remove, staging kept, exception re-raised).
    Unconfirmed -> `stop_unconfirmed` with the recovery reference; worker raises the existing
    unknown-outcome `ContractError`, verifier returns `container_stop_unconfirmed` (never `checked`).
    The former private stop inside `_converse` was removed in favour of this one rule.
  - `retire` writes retained files and `evidence_retained` first, removes the exact container second,
    then `removed`. A failed write removes nothing: worker raises `ContractError` (record stays
    `imported`, container and staging retained), verifier returns `replay_evidence_unwritten`.
  - Worker evidence: `run.json` `result` as before plus `retained_files["inner_result.json"]`
    `{file,sha256,bytes}`: the WHOLE inner result (events included) after token redaction.
    Verifier evidence: `replays/<run_id>/run.json` `result` = bounded capture output + container
    context; only the snapshot copy is deleted after removal, the record stays (`removed`).
  - Restart visibility: an unresolved verifier record refuses the next replay
    (`isolated_replay_unavailable: isolation_unresolved_run`, nothing created) and, through
    `IsolatedWorker` -> `watch=(replays,)`, the next worker run of that workspace. `reconcile
    <replays>/<run_id>` works unchanged; `status <runs-dir> <replays-dir>` accepts several roots.
  - `stop(window)`: every inspect/kill timeout is `min(docker_command_seconds, remaining window)`;
    no call begins after the deadline; kill is attempted once even when inspect gave no answer.
    Outside the declared window and still bounded: worker client-tree terminate (its own 20s+10s)
    and `remove` (rm + ps, `docker_command_seconds` each), both after the stop decision.

Injected vs actual. Everything this worker observed is INJECTED: `FakeDocker`, a fake `_capture`
raising `KeyboardInterrupt` after marking the fake container running, `kill_works=False`,
`_write_record` raising `OSError`, a synthetic verifier record, a raising `on_tick` over a real local
non-model child process. None is an observation of a real container. New tests (all labelled):
evidence: normal replay record, interruption -> removed, interruption + unconfirmed stop -> durable
recovery record/refused next replay/reconcile, returned capture + unconfirmed stop, evidence-write
failure; worker: full inner result before `rm`, evidence-write failure, observer failure, verifier
record refusing the worker, stop timeouts bounded by the window.

Owner-only, still required (not run here): rebuild `Dockerfile.worker` capturing the docker child exit
directly and `docker run --rm --entrypoint claude <id> --version`; `uv run pytest -q` and CI; rerun
`artifacts/isolated-worker-001/review-cancel.py` (REAL docker start + injected interrupt) expecting no
running container and either a `removed` record or a `stop_unconfirmed` one; the Docker-marked test on
Windows and WSL; `status` over both roots printing `[]`; then the actual model canary and its review.
Uncertain: whether `claude --version` needs a writable HOME during the uid-10001 build step (it has
`/home/worker`); a second interrupt arriving inside `hold`'s finally leaves the record at
`start_requested`, which is durable and unresolved but the container may still run.

## Image and capture ownership reframe (SPEC final section)

Disposition: improve the existing authorities (`evidence_inspection._capture`, `hold`,
`Dockerfile.worker`); reuse `ProcessTree`; no new supervisor, retry or fallback. Files:
`Dockerfile.worker`, `adapters/evidence_inspection.py`, `adapters/isolated_worker.py` (`hold` only),
the three test files, `docs/contracts.md`, this report. `isolated_evidence.py`, `worker_profile.py`,
profile bytes, host interpreter policy, permission grants, replay policy/authorization and default
host mode are untouched. Rollback: revert this change; nothing persisted changes shape except the
optional `cleanup`/`capture_cleanup` fields below.

- **Image.** `python -m venv --copies --without-pip /opt/zeus` runs before `uv sync` (same
  `UV_PROJECT_ENVIRONMENT`), and the same RUN fails if `/opt/zeus/bin/python` is a symlink or its
  realpath leaves `/opt/zeus/bin` (guards against uv recreating a symlinked venv). As uid 10001,
  after the retained Claude `2.1.274` check, one build step calls the real `verified_interpreter()`,
  `profile_environment(child_environment()[0], '/workspace', interpreter)`, requires the interpreter
  and the `python` found through THAT PATH to live in `/opt/zeus/bin`, and runs
  `python -m pytest --version` and `python -m ruff --version` under exactly that environment with
  `check=True`. No credential, network or model call. NOT built or run by this worker.
- **Capture.** `_capture` spawns through `ProcessTree.spawn` (job object / process group, replacing
  the private `CREATE_NEW_PROCESS_GROUP` + `taskkill`/`killpg`). One `_reclaim(tree, readers, reason)`
  runs on every exit of the wait: `tree.terminate` (10s + 10s) -> one shared 5s reader join -> close
  only streams whose reader finished (an unstarted reader owns nothing) -> `tree.close()`. Normal exit
  first gives readers the former 5s to drain, then reclaims stragglers. `TimeoutExpired` keeps the
  exact former failure text; any other `BaseException` is re-raised unchanged after `_reclaim`, with
  the record on `exc.capture_cleanup`. Unconfirmed cleanup on a returned capture appends
  `capture_cleanup_unconfirmed: ...` to `failure` (so `classify_replays` -> `replay_failed`) and the
  run carries `cleanup`; `cleanup` is also present on timeout, absent on a clean normal run, so normal
  stream receipts (sha256/bytes/truncated/decoding/raw) and classification are unchanged. A
  `TreeOwnershipError` at spawn is a `spawn_error` failure. Errors inside `_reclaim` are recorded, not
  raised, so `hold`'s container stop always follows.
- **hold.** Reads `capture_cleanup` from the propagating exception, stores it in the stop record, and
  treats unconfirmed client debt as not confirmed: `stop_unconfirmed` + recovery reference, container
  still stopped, nothing retired. Confirmed -> `removed` with `result.stop.capture_cleanup`.
- **Suite compatibility.** `test_staging_is_a_detached_export...` names the generated fixture file via
  `stage.joinpath("src", "pkg", "mod.py")` outside the assert; the byte-copy assertion is kept, the
  architecture guard is unchanged.

Tests (real helper, real child `HOLDER` = python child + sleeping grandchild sharing the pipes; the
interruption is INJECTED on the real returned process's first `wait`; a 60s watchdog is asserted
never to fire): normal receipts; timeout -> tree confirmed, both streams closed, `started` kept;
interruption -> original KeyboardInterrupt, cleanup confirmed, pipes at EOF and closed; INJECTED
no-op terminate -> no close behind live readers, `replay_failed`; through `DockerEvidenceInspector`
with the real `_capture`: container stop reached with the child already gone, record `removed`;
INJECTED unreclaimed debt -> `stop_unconfirmed`, no `rm`. All local-child/FakeDocker evidence on
Windows only; POSIX group path of these tests not run here. The old behaviour was not re-run in a
disposable copy (the lead's preserved reproducer is the before-evidence); owner reruns it.

Owner-only, not run here: image build + the repeated no-credential probes, `uv run pytest -q`/full
suite (`tests/test_architecture.py` alone was run here and passed), the lead's real-capture reproducer, real Docker
outer-cancellation check, canary. Uncertain: uv reusing the stdlib `--copies` venv (build guard fails
loudly if not); copied interpreter locating libpython (owner's experiment passed); a worst-case
teardown is bounded (~25s) but longer than the declared container cleanup window that follows it.
