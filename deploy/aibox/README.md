# Zeus on aibox: Linux service templates and lifecycle inspection

Scope: SPEC-retirement-update s5 (network) and s9 (Linux lifecycle) of aibox-migration-001.
These files are templates and read-only tooling. Nothing here installs, enables, starts or
stops a unit, and nothing here changes admission, the Fleet registry, Docker or the network.
Every command below that changes the host is an owner action at the gate named beside it.
The core coordinator contract is in [INTEGRATION-CONTRACT.md](INTEGRATION-CONTRACT.md).

## Files

| Path | Role |
|---|---|
| `systemd/zeus-aibox-fleet.service.in` | the ONE owner of `zeus fleet run` |
| `systemd/zeus-aibox-monitor-collect.service.in` | read-only monitor collector |
| `systemd/zeus-aibox-monitor-web.service.in` | monitor page, `127.0.0.1` only (harness-fixed bind) |
| `systemd/zeus-aibox-inspect.{service,timer}.in` | read-only lifecycle inspection every 5 min |
| `systemd/zeus-aibox.target.in` | groups the three services (`PartOf=`) |
| `systemd/zeus-aibox-managed-fleet.service.in` | owner-fixed unit of the managed Fleet target (SPEC s14 G3); started by HostDelivery only |
| `systemd/zeus-aibox-owner-actions.service.in` | server-owned research-acceptance / plan / canary coordinator (SPEC s14 G1/G2) |
| `polkit/50-zeus-aibox-managed-fleet.rules.in` | `start` of exactly the managed Fleet unit for the service user; nothing else |
| `env/zeus-aibox.env.example` | non-secret settings; secret names only |
| `zeus_aibox_service.py` | render / verify / launch / journal / inspect / network / host-id (stdlib) |

## Layout on aibox (SPEC s4)

```
/srv/zeus/deploy/aibox/            copy of this directory at the accepted revision
/srv/zeus/releases/<40-hex>/       immutable runtime; .venv built in place (uv sync --frozen)
/srv/zeus/releases/current         pointer; resolved once per start, pinned by activation receipt
/srv/zeus/runtime/control/         WorkingDirectory, HARNESS_RUNTIME_DIR, journal, fence, receipt
/srv/zeus/config/zeus-aibox.env    0640, non-secret
/srv/zeus/secrets/zeus-aibox.env   0600, service UID, secrets only (never Environment= lines)
```

## Render and verify (offline, no installation)

```bash
python3 deploy/aibox/zeus_aibox_service.py render --output /srv/zeus/tmp/units-<run> \
  --root /srv/zeus --user trevi --uid 1000 --home /home/trevi
python3 deploy/aibox/zeus_aibox_service.py verify /srv/zeus/tmp/units-<run> --systemd-analyze
```

`render` requires an explicit non-root `--uid` and checks it (and the home) against the account
database. Paths must be absolute literals: no whitespace, `%` specifiers or `$` expansions, and no
Windows or `/mnt/<drive>` entries in PATH. It refuses any live systemd directory as output and
writes `render-manifest.json` with every file's sha256. `verify` applies the static policy below,
and with `--systemd-analyze` it runs `systemd-analyze verify` on the rendered files only. That
command also loads the host's installed units. Their warnings are counted separately and do not
decide the verdict.

Static policy per service: explicit `User`/`Group` (non-root), absolute `WorkingDirectory` and
`Exec*`, exactly one absolute `PATH=`, no secret-named `Environment=`, no `resume`,
`KillMode=control-group`, final SIGKILL, `TimeoutStopSec` of 900 s or less, `Restart=on-failure`,
`StartLimit*`, `RestartPreventExitStatus=78`, and no LAN IPv4 literal or Windows path anywhere.

## Lifecycle semantics

* **Single owner.** `zeus-aibox-fleet.service` is not a template, so systemd never runs two.
  `inspect` also reports any `... zeus fleet run` process outside that unit's cgroup (a manual
  `fleet run --once`, an old launcher) as `fleet_runner_outside_unit`, and more than one runner
  inside it as `multiple_fleet_runners_in_unit`. The application lease and fence stay in force.
  This file does not replace them.
* **Explicit environment.** `User=`, `SupplementaryGroups=docker`, `HOME`, `PATH`, `LANG`,
  `WorkingDirectory` and absolute `ExecStart` come from the unit, with no login shell, profile
  or inherited PATH. The launcher refuses a relative or Windows PATH entry.
* **Launch gate (exit 78, never restarted).** The launcher refuses in these cases: `host-fence.json`
  exists (any role); `releases/current` is not a 40-hex revision with a venv and package; for the
  Fleet, `host-activation.json` is missing or names another host, revision or state.
* **Paused bootstrap.** The Fleet starts against a registry that is already paused, and nothing
  here resumes it. The owner widens admission with `zeus fleet resume` after the read-only
  monitoring check.
* **Bounded stop.** `SIGTERM` makes `FleetRunner.stop()` close admission and drain owned children.
  After `TimeoutStopSec=180` everything left in the unit cgroup gets SIGKILL. A job cut off that way
  is interrupted: recover it with `zeus fleet reconcile-interrupted` and never retry it blindly. For a
  planned stop, first `zeus fleet pause` and wait until every lane `active_job` is null.
* **Bounded restart.** `Restart=on-failure`, `RestartSec=15`, at most 3 starts in 600 s. After
  that the unit stays `failed` for a human (`systemctl reset-failed` is an owner action).
* **cgroup vs Docker.** `KillMode=control-group` ends the unit's processes, including `docker`
  client processes. Worker containers belong to `dockerd`'s scope and survive. `inspect` shows
  each labelled container's real cgroup, and `labelled_containers_without_active_owner` is the
  residue signal. Reconcile it by the `zeus.isolated.run` label through the harness. These tools
  never stop or remove a container.
* **Lifecycle journal.** `ExecStartPre`/`ExecStopPost` append `start`/`exit` (by systemd
  `INVOCATION_ID`) to `runtime/control/fleet-service-journal.jsonl`. That is the `--journal`
  that `zeus fleet relocate` requires.

## Install order (owner actions; not executed by this task)

1. Gate N passed on the current LAN. Copy this directory to `/srv/zeus/deploy/aibox` and record
   its hash. Build `releases/<rev>/.venv` in place and point `current` at `<rev>`.
2. Create `config/zeus-aibox.env` (0640) and `secrets/zeus-aibox.env` (0600, service UID).
3. Render, verify, then `sudo install -m 0644` the rendered units into `/etc/systemd/system`,
   followed by `sudo systemctl daemon-reload`.
4. Start the monitors first: `systemctl start zeus-aibox-monitor-collect zeus-aibox-monitor-web`,
   then `systemctl enable --now zeus-aibox-inspect.timer`.
5. When the coordinator reaches `restored_paused` it writes `host-activation.json`. Then
   `systemctl start zeus-aibox-fleet`. Confirm the Fleet is paused (`zeus fleet status`) and run
   `inspect`. Enable `zeus-aibox.target` only after A acceptance.

## Managed Fleet and owner actions (SPEC s14; owner actions, not executed by this task)

- Only one Fleet runner exists: writing `runtime/control/fleet-owner.json`
  (`{"schema": "urn:zeus:aibox-fleet-owner:1", "owner": "managed-fleet",
  "unit": "zeus-aibox-managed-fleet.service"}`) retires the bootstrap `fleet` role (it then refuses
  `fleet_owner_managed`). The managed role starts only while `zeus-aibox-fleet.service` is inactive.
- The managed target's registry entry is kind `managed_fleet_systemd`, `service`
  `zeus-aibox-managed-fleet` and `state_dir` `<root>/runtime/managed-fleet`. `releases/current` stays the
  stable controller code. The candidate runtime is the descriptor's sealed root and its startup receipt.
- Install the rendered polkit rule only together with the managed unit. The delivery controller never
  stops that unit: a managed stop is the target's graceful pause/idle/stop file.
- `zeus-aibox-owner-actions.service` needs `ZEUS_OWNER_ACTIONS_POLICY` in the non-secret config and a
  registered owner policy (`zeus owner-actions register`). An idle tick calls no model.

## Monitoring without Windows

The collector, web page and inspection timer run on aibox under systemd. They need no Windows
host, SSH session or Codex desktop session (SPEC B5). A person views the page through
`ssh -L 8787:127.0.0.1:8787 aibox`. Evidence stays in the journal
(`journalctl -u 'zeus-aibox-*'`) and in `runtime/control/lifecycle-inspection.json`. `inspect`
reports `windows_observer: not_observable_from_aibox`: the Windows fence is proved by the
coordinator's source receipt, not from here.

## Current LAN now, IP change later (SPEC s5)

Nothing in the units or the config holds a LAN address. DB and Redis are loopback or Docker
service names, the web page is loopback, and host identity is `host-id` (machine-id digest).
`inspect` flags any LAN IPv4 literal found in installed unit/config files.

```bash
# on the current LAN, before migration: record a baseline (addresses and default route only)
python3 /srv/zeus/deploy/aibox/zeus_aibox_service.py network --record /srv/zeus/artifacts/<task>/network-before.json
# the later IP change maintenance
zeus fleet pause           # then wait for every lane active_job == null
# ... switch / DHCP reservation / Windows SSH alias HostName (keep HostKeyAlias) ...
python3 /srv/zeus/deploy/aibox/zeus_aibox_service.py network --baseline /srv/zeus/artifacts/<task>/network-before.json
python3 /srv/zeus/deploy/aibox/zeus_aibox_service.py inspect
# re-verify SSH both ways, model/GitHub HTTPS, NTP, route overlap; then the owner runs `zeus fleet resume`
```

An IP change needs no re-render, no data re-migration and no service restart for correctness.
Only the changed boundaries and failed checks are re-verified.

## Not verified here

Units were rendered and verified offline only. No unit was installed or started on aibox, so the
real stop/SIGKILL timing, restart limits, `ProtectSystem=full` + Docker socket interaction,
polkit/sudo privilege, cold boot and actual container residue after a real stop are all
unverified. They belong to the A5 run on aibox.
