# aibox service integration contract (for the core migration author)

Status: proposal delivered with the Linux service templates; nothing here is implemented in
`src/codex_harness`. The core migration coordinator and any systemd HostDelivery target are owned
by the core session. This file states what the templates in `deploy/aibox/` expect from it and
what they give back, so the two halves can be joined without either one editing the other.
SSOT: `SPEC-retirement-update.md` s4, s6, s9, s10 (aibox-migration-001).

## 1. What the templates provide

| Item | Where | Meaning |
|---|---|---|
| Single Fleet owner | `zeus-aibox-fleet.service` | non-template unit; systemd refuses a second instance |
| Launcher | `zeus_aibox_service.py launch --role R` | fail-closed checks then `execve` of the pinned release |
| Lifecycle journal | `runtime/control/fleet-service-journal.jsonl` | `start`/`exit` lines keyed by systemd `INVOCATION_ID` |
| Inspection | `zeus_aibox_service.py inspect` (+ 5 min timer) | read-only owner/cgroup/Docker/fence/network JSON |
| Host identity | `zeus_aibox_service.py host-id` | `machine-id-sha256:<hex>`; never the IP, never the raw id |

The journal format is exactly what `adapters.fleet_recovery.runner_state` reads (tested against
that function). Pass it to `zeus fleet relocate --journal <root>/runtime/control/fleet-service-journal.jsonl`.
`exit` is written by `ExecStopPost`, which systemd runs after the unit's control group is empty or
SIGKILLed. It is NOT evidence that Docker containers ended (s4 below).

## 2. What the core coordinator must write (files under `<root>/runtime/control/`)

### 2.1 `host-activation.json` - required for the Fleet role only

```json
{"schema": "urn:zeus:aibox-host-activation:1",
 "migration_id": "<coordinator migration_id>",
 "host_id": "machine-id-sha256:<output of host-id on aibox>",
 "state": "restored_paused | limited_active | qualified",
 "release_revision": "<40-hex; basename of releases/<rev>>"}
```

Additional fields (transition receipt digest, actor, UTC, config/image/profile hashes) are allowed
and ignored by the launcher. Write it atomically (temp file, fsync, rename) at the coordinator's
`restored_paused` transition, after restore and hash comparison. The launcher refuses (exit 78, not
restarted) when the file is missing, unreadable, names another host, another revision, or any
other state. So a `current` symlink change alone never starts a different revision: the receipt
must move with it (SPEC s10 "`current` symlink change alone is not acceptance").

Monitor roles do not require it: read-only monitoring must work before activation and while fenced.

### 2.2 `host-fence.json` - presence refuses every role

Existence alone refuses the launch, even when the file cannot be parsed. Content is advisory for
humans (`migration_id`, `reason`, `at`). The coordinator writes it on this host at R0/R1 rollback
target-fence and whenever this host must not own anything. Removing it is an owner action.
Stopping the running unit is a separate step: the launcher only gates a start. `inspect` reports
`fleet_active_while_fenced` when the unit is still running beside a fence.

The Windows source fence is outside this directory and these templates. aibox cannot observe the
Windows observer (`windows_observer: not_observable_from_aibox`). The coordinator's source-fence
receipt stays the evidence for A1.

### 2.3 Paused bootstrap

The restored Fleet registry must already be paused in PostgreSQL (`zeus fleet pause` before the
snapshot, preserved by restore). Nothing in the templates calls `fleet resume`, and static
verification rejects any unit directive that mentions `resume`. Admission is widened only by the
owner through `zeus fleet resume` after the read-only monitoring check (SPEC s10).

## 3. Release layout the launcher requires

```
<root>/releases/<40-hex>/.venv/bin/python     # `uv sync --frozen` run AT this path
<root>/releases/<40-hex>/src/codex_harness/__init__.py
<root>/releases/current -> <40-hex>           # resolved once per start
```

A venv is not relocatable (absolute shebangs). Build it in place, never copy it from Windows or
from another path. The launcher sets `ZEUS_REPOSITORY`/`HARNESS_REPOSITORY` to the release,
`HARNESS_RUNTIME_DIR=<root>/runtime/control` (from the unit), `VIRTUAL_ENV`, and prepends the venv
`bin` to the explicit unit PATH. `.env` is therefore read from the release root. Keep none there:
secrets come from the unit `EnvironmentFile` and environment overrides `.env` (configuration.settings).

## 4. Docker ownership caveat (A5)

`KillMode=control-group` ends every process in the unit cgroup, including `docker` client
processes. Worker containers are children of `dockerd` (`/system.slice/docker-<id>.scope`), so
they are NOT ended by stopping the unit. `inspect` shows each `zeus.isolated.run` container's real
cgroup and reports `labelled_containers_without_active_owner` when any is running while the Fleet
unit is inactive. Reconciliation stays in the harness: `isolated_worker` run records plus
`zeus fleet reconcile-interrupted`. These tools never `docker stop/rm` and never mark an effect
successful.

## 5. Proposed systemd HostDelivery target (core author decides; not implemented here)

The SPEC (s2) leaves open whether `ProcessHostTarget` is reused or a systemd adapter is added. If
one is added, the templates support this minimal mapping onto `HostTargetBase`:

| HostTargetBase hook | systemd realisation |
|---|---|
| `running(target)` | `systemctl show <unit> -p ActiveState,MainPID,InvocationID`; `active`/`activating`/`deactivating` = running |
| `stop(target)` | `systemctl stop <unit>`, then a bounded wait for `inactive`/`failed` of at most `TimeoutStopSec` (180 s) + margin; report `{stopped, was_running, invocation_id}`; unconfirmed = not stopped |
| `_launch(...)` | the coordinator writes/updates `host-activation.json` for the new revision under the target guard, repoints `current`, then `systemctl start <unit>`; record `InvocationID` + `descriptor_sha256` in `controller-state.json` |
| startup identity | the existing startup receipt written by the service, plus the unit `InvocationID`; never the unit's active state alone |

Open requirements for that adapter, all outside this allocation:

* **Privilege.** These are system units with `User=`. `systemctl start/stop` needs root or an
  owner-approved polkit rule restricted to `zeus-aibox-*.service` for the service UID. Neither is
  configured here, and choosing one is an owner decision.
* **Stop semantics.** SIGTERM triggers `FleetRunner.stop()` (admission closes, owned children
  drain). A drain longer than `TimeoutStopSec` ends in SIGKILL of the cgroup. The job becomes
  interrupted, the container may survive, and recovery is `fleet reconcile-interrupted`. Planned
  stops therefore pause first and wait for every lane `active_job` to be null.
* **Restart budget.** `StartLimitBurst=3` in 600 s. After that the unit stays `failed` until a
  human runs `systemctl reset-failed`. The adapter must not reset it automatically.

## 6. Values the core must not assume

* A LAN IP is never an identity: host identity is `host-id`, and DB/Redis addresses are loopback
  or Docker service names. `inspect` flags LAN IPv4 literals in installed unit/config files.
* `systemctl restart` succeeding is not reboot evidence. Cold boot stays unverified.
* A unit that is `active` is not a healthy Fleet: the Fleet projection and receipts decide that.
