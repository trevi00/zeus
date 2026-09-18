# Report + background 001 — backend lane notes (silent host children)

Frame: SPEC.md, Backend lane only. Base f067bb633831363348ad3108b6382a580cb723f8. Worker: Linux
(WSL2 kernel, Python 3.13.15); the native Windows console tests below were not executed here.
Disposition: improve the existing mechanism. `commands.run_process` already owned the Windows
process group and the `taskkill` path; the console policy is added to it and reused, not a second
spawn mechanism. No cancellation rewrite, no `shell=True`, no new scheduling, no UI edit.

## The one helper

`codex_harness.adapters.commands.no_console_kwargs(*, process_group=False, creationflags=0,
platform=None) -> dict` (platform defaults to `os.name`; the parameter exists for tests only).

| host    | `process_group=False`             | `process_group=True`                                  |
|---------|-----------------------------------|-------------------------------------------------------|
| Windows | `{"creationflags": CREATE_NO_WINDOW \| creationflags}` | `... \| CREATE_NEW_PROCESS_GROUP` |
| POSIX   | `{}`                              | `{"start_new_session": True}` (unchanged)             |

CREATE_NEW_CONSOLE and DETACHED_PROCESS are never added (Windows ignores CREATE_NO_WINDOW next to
either; SPEC sources). `CREATE_NO_WINDOW`/`CREATE_NEW_PROCESS_GROUP` are read from `subprocess`
with their Win32 values as the fallback so the policy is describable from Linux. The helper is only
for children whose stdio is redirected; every listed call site pipes or captures.

## Applied paths (complete listed matrix, each preserving its existing flags and ownership)

- `commands.py`: `run_process` child (group + no window) and its timeout `taskkill`.
- `fleet_runtime.py`: `LaneLauncher.launch` child (group + no window; stdin DEVNULL, log files, cwd, env).
- `app_server.py`: `AppServer.__enter__` codex app-server (group + no window) and `__exit__` `taskkill`.
- `isolated_worker.py`: `list_revision`, `stage_source` (`git cat-file --batch` Popen),
  `init_standalone_git` (env allowlist kept), `IsolatedWorker.run` `rev-parse`/`status --porcelain`.
- `operation_cli.py`: `GitSource._run`. `source_verification.py`: `GitSourceVerifier.git`.
- `source_execution.py`: `bounded_command` (docker run); the `docker rm` cleanup already went
  through `run_process`.
- `process_tree.py`: Windows branch `CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`
  via the helper; suspended start, job assignment, verified membership, resume order and the
  failure cleanup are untouched. The POSIX branch (`start_new_session=True`) is untouched.
- `published_ports.py` `_run`, `port_diagnosis.py` `_run`: docker/wsl.exe/netsh probes.
- `audit_runner.py` `acquire`: `git init --bare`, `remote add`, `cat-file -e`.

Not changed: launch scripts (`scripts/*.ps1`, owner deployment configuration), any module outside
the listed eleven (e.g. `git.py`, `claude_cli.py`, `evidence_inspection.py` spawn through
`run_process`/`ProcessTree` and inherit the policy; other direct `subprocess` uses elsewhere were
not audited and are not claimed).

## Tests: `tests/test_background_processes.py`

- Helper policy with injected platform: Windows flags, cancelling flags absent, POSIX has no
  Windows keyword; a real child on the running host keeps UTF-8 output and exit 3.
- Wiring with the platform injected into the helper (module `os` shim) and `subprocess.Popen`/
  `run` replaced by a recorder that refuses to start anything: `run_process` + `taskkill`, fleet
  lane child, app-server + `taskkill`, `ProcessTree.spawn` Windows branch (job object faked:
  labelled injection), `GitSource`, `GitSourceVerifier`, `AuditRunner.acquire`, published-port and
  port-diagnosis probes, `bounded_command`, `list_revision`, `init_standalone_git`, `stage_source`.
- Source audit (AST) over the eleven modules: every `subprocess.run/Popen/...` call carries
  `**no_console_kwargs(...)`, except exactly the one POSIX-only `start_new_session` branch in
  `process_tree`; no `shell=` keyword; no `CREATE_NEW_CONSOLE`/`DETACHED_PROCESS` name in code.
- Native Windows (skipped elsewhere): `run_process` child reports `GetConsoleWindow()==0`, prints
  `한글 출력` intact and exits 3, with a labelled control (same child without the policy shows a
  non-zero handle, asserted only when the test process itself has a console); `ProcessTree.spawn`
  child reports 0 inside a verified job object and terminates confirmed; the timeout `taskkill`
  carries CREATE_NO_WINDOW.

## Executed here (Linux worker) and observed

```
python -m pytest tests/test_background_processes.py tests/test_claude_review_boundaries.py tests/test_fleet_runtime.py tests/test_app_server.py -q -p no:cacheprovider
```
65 passed, 6 skipped (3 native Windows console tests here; 3 pre-existing Windows job-object tests).

```
python -m pytest tests/test_isolated_worker.py tests/test_port_diagnosis.py tests/test_published_ports.py tests/test_operation_cli.py tests/test_research_audits.py tests/test_claude_cli_process.py tests/test_evidence_inspection.py -q -p no:cacheprovider
```
202 passed, 2 skipped (Docker owner check; integration environment). `python -m ruff check .` clean.

Detection evidence for the audit test: during development it failed on the partially wired tree
naming `app_server:81` (helper passed through a local variable) and `process_tree:247` (POSIX
branch), so it does observe an unrouted spawn; a run against the untouched base in a disposable
copy was not possible (only pytest/ruff/read-only git are permitted to this worker).

## Not run by this worker (owner)

Native Windows console probes (the three skipped tests), Windows CI, the full suite, real
`zeus operate run`, Docker/provider children, model calls. No window/handle measurement on the
owner's host was taken here; the SPEC's statement that not every observed flash is proven to come
from Zeus stands. Scheduled launcher entry (no-window creation at the task level) is owner
configuration outside the repository.
