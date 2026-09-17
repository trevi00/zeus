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
5. Canary: `zeus operate run <manifest>`; then `python -m codex_harness.adapters.isolated_worker status <runtime>/isolated-worker/runs` must print `[]`
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
  (3) If `on_tick`/observer raises mid-run the container is stopped but its record stays `running`
  and needs `reconcile` after the owner removes the exact container. (4) Hook receipts missing is
  reported (`observed:false`), not turned into a failure, matching the host runtime. (5) Bind sources
  containing a comma are unsupported by `--mount` syntax. (6) Worker egress is unrestricted bridge networking (SPEC).
