"""Buzz D2: the owner-run isolated end-to-end on the disposable stack (compose project `zeus-buzz-e2e`).

A standalone runner, NOT collected by pytest (the name is not `test_*`; the A4 rule, D-A4-1: no conftest applies, so the
R-P Docker guard is neither imported nor bypassed). The owner runs it from `target/` with the target venv:

    uv run --frozen python -B tests/fixtures/buzz_e2e/run_e2e.py [--report PATH] [--keep-on-failure] [--desktop DIR]

It starts `compose.yaml` beside it (the A4 relay stack plus `zeus-postgres` on its own network; every image pinned by
digest, every port published only on 127.0.0.1:<ephemeral>), seeds a fixture Zeus into `zeus-postgres` through the
target's own `Workflow`/`FleetRegistry`, starts the Buzz bridge (D1 entry) as a subprocess, and drives the Desktop's own
Zeus logic (the D3 owner driver, Node) against the real relay. Its working directory is
`/home/trevi/workspaces/zeus/scratch/buzz-e2e/<UTC stamp>` (mode 0700; never /tmp). The explicit list of docker argv
forms it uses (`DOCKER_FORMS`) is printed in the report header and stored in the report for audit.

Exit codes: 0 every asserted step passed; 1 a step failed (its name is printed); 2 a precondition refusal (step 1).
Cleanup runs in `finally` unless `--keep-on-failure` is given and a step failed: every child process group is killed,
`down -v` runs, the residue check (containers, networks, volumes, processes) runs, and the secrets of the work dir
(keys, DSN, env and owner-key files) are deleted. Never run by the worker that wrote it: the OWNER runs Docker.

Every subprocess (docker, the bridge, the fixture attempt workers, the owner driver) is started by `Procs` in its own
process group (`start_new_session=True`) and is killed in `finally`. No key, DSN or password value is printed or put in a
report line (they are scrubbed); no secret or credential path is on the argv of the bridge, a worker or the driver
(`scan_argv`, recorded in the report).

Fixture Zeus (DESIGN-D §4): `PostgresStore.migrate()` on `zeus-postgres` (DSN in a 0600 file), an organization of 1
conductor, 2 leads and 3 workers in two teams (`organization.json`, packaged-style ids with `:`), a registered fleet, tasks
`t1` (lead -> worker, queued), `t2` and `t3` (claimed with a live lease and a fence generation).
- Claim path (named from code): `Workflow.claim` (coordination/application/workflow.py) -> `execution_fence.advance`
  (INV-EXECUTION-IDENTITY-001); the holder's guard is `execution_fence.require_current`; a cancel advances the fence
  through `MessageHandler.cancel_in` (coordination/application/messages.py).
- Admission path (named from code): `AdmissionControl.reserve_unit`/`admit_one` (coordination/application/fleet/
  admission.py) read the pause and refuse `FleetRefused("paused")`. `Workflow.claim` reads no pause at all: the task
  admission row of a paused fleet is MISSING in the target (DESIGN-D §8) and the report says so in step 6.
- `t3` is the fixture WORK of steps 6 and 9 (`t2` is cancelled in step 5, so it cannot be the running work afterwards).
- Custody names: every role key is created under `custody_name(role_id)` (composition.buzz_bridge) in the bridge's
  custody directory; the bridge AUTHs (NIP-42) and signs with its conductor key (DESIGN §6.2.1), so the relay needs no
  further membership and no key is copied.

Steps (A = asserted, R = recorded in the report; a failing step is named and the run goes on):
 1 preconditions  A: docker, node and the D3 driver exist; digests pinned; no resource of this project exists (a foreign
                     one is never cleaned); free loopback ports.
 2 stack+fixture  A: keys (0600), env file 0600; relay and zeus-postgres healthy; hardening (no privileged/host/socket/
                     cap_add, loopback ports); migrate + seed; relay bootstrap: owner AUTH, 9030 (conductor, stranger),
                     private channels (commander + one per team) via 9007, conductor/owner joined via 9000.
 3 N1,N2          A: after <= 3 active ticks the driver's `org` is `verified` with 1/2/3 and `card t1`/`card t2` are
                     verified with their task roots.
 4 N3,N4          A: `cancel_task t1`: effect_done receipt, `state` done, ONE effect (one transition, generation +1); the
                     same command event republished -> `duplicate:` and no second effect.
 5 T2             A: `cancel_task t2`: the fence generation advances, the fixture attempt's guard is REFUSED (`fence_lost`),
                     the card shows `cancelled`.
 6 T3             A: `pause_fleet` done; fleet admission refuses `paused` (reserve_unit); `t3` keeps running; the card/org
                     interventions offer `resume_fleet`; `resume_fleet` done; admission opens. R: the missing task admission.
 7 N4 (desk)      A: `desk_turn` -> `refused: desk_not_migrated`, nothing else changed.
 8 S1/F1          A: a stranger-signed and a conductor(role)-signed command fence -> no effect, no transition, no receipt.
 9 C2             A: SIGTERM between ticks and mid-pass: exit 0 within recv_timeout + one step; `t3` completes while the
                     bridge is down; a command published while it is down is admitted after the restart (cursor).
10 R3             A: SIGKILL right after a command's inbox commit; after the restart exactly one effect and one receipt.
11 R4             A: a second bridge with the same config stays passive (no pass, no commit) while the first holds the lease.
12 C4             A: `down -v`; zero residue (containers, networks, volumes, processes); secrets removed.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # attempt_worker (the fixture Zeus builders)
sys.path.insert(0, str(HERE.parent / "buzz_conntest"))  # run_matrix's helpers (never modified)

import attempt_worker as fz
from run_matrix import HARDENING_FORMAT, HEALTH_SECONDS, MAX_SIZE, PACE_SECONDS, STATE_FORMAT, Refusal, free_port

from codex_harness.composition.buzz_bridge import (
    STOP_MARGIN_SECONDS,
    STORE_CONNECT_SECONDS,
    BridgeConfig,
    custody_name,
    stop_bound_seconds,
)
from codex_harness.coordination.application import execution_fence
from codex_harness.coordination.application.bridge_lease import BUCKET as LEASE_BUCKET
from codex_harness.coordination.application.bridge_lease import FENCE_ROW
from codex_harness.coordination.application.fleet import state as fleet_state
from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.remote_control import COMMANDS, TRANSITIONS
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.credentials.adapters.role_keys import TestRoleKeys
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.observation.adapters.buzz_relay import BuzzRelayClient
from codex_harness.observation.adapters.event_signer import NostrEventSigner
from codex_harness.observation.adapters.nostr_verify import verify_event
from codex_harness.observation.domain.buzz_projection import NS_ZEUS_BUZZ
from codex_harness.storage.adapters.postgres_store import PostgresStore

PROJECT = "zeus-buzz-e2e"
LABEL = f"label=com.docker.compose.project={PROJECT}"
COMPOSE = HERE / "compose.yaml"
ORGANIZATION = HERE / "organization.json"
WORKER = HERE / "attempt_worker.py"
SCRATCH = Path("/home/trevi/workspaces/zeus/scratch/buzz-e2e")
NODE = "/home/trevi/.local/share/fnm/node-versions/v24.21.0/installation/bin/node"
DEFAULT_DESKTOP = Path("/home/trevi/workspaces/zeus/worktrees/buzz-desktop-001")
DRIVER = "src/features/zeus/e2e/driver.mjs"
SCHEME = "postgresql" + "://"  # split: the tree check flags credential-shaped literals
TICK = 2  # bridge tick_seconds
LEASE_TTL = 8  # lease_ttl_seconds: must exceed three ticks
RECV_TIMEOUT = 3  # recv_timeout
STOP_BOUND = RECV_TIMEOUT + TICK + 5  # DESIGN-D §2: recv_timeout + one step (the step bound is generous: PG + relay)
COMMAND_WAIT = 60  # a command's receipts within 60 s
ORG_D = str(uuid.uuid5(NS_ZEUS_BUZZ, "zeus.org:e2e"))  # canonical UUID: the relay refuses any other `d`
TEAMS = ("alpha", "beta")
CHANNELS = ("commander", *TEAMS)
TASKS = (("t1", "lead:alpha", "worker:alpha-1"), ("t2", "lead:alpha", "worker:alpha-2"),
         ("t3", "lead:beta", "worker:beta-1"))
PROBE_UNIT = hashlib.sha256(b"zeus-buzz-e2e admission probe").hexdigest()  # UNIT_ID: 64 hex
OUTSIDE_ROLES = ("owner", "stranger", "relay")  # keys the bridge's custody never holds
SECRET_NAME_PARTS = ("dsn", "password", "secret", "private", "hex")  # identifiers the static test keeps out of print/log

# The explicit docker argv forms the runner uses (without the `docker` word); `<...>` marks the variable parts. The static
# test matches this list against every `.compose(...)`/`.docker([...])` call of this file (AST).
DOCKER_FORMS = [
    "compose -p zeus-buzz-e2e -f <compose.yaml> --env-file <env file> up -d",
    "compose -p zeus-buzz-e2e -f <compose.yaml> --env-file <env file> ps -q <service>",
    "compose -p zeus-buzz-e2e -f <compose.yaml> --env-file <env file> ps -a -q",
    "compose -p zeus-buzz-e2e -f <compose.yaml> --env-file <env file> logs --no-color --tail 200 relay",
    "compose -p zeus-buzz-e2e -f <compose.yaml> --env-file <env file> down -v --remove-orphans",
    "ps -a -q --filter <label>",
    "network ls -q --filter <label>",
    "volume ls -q --filter <label>",
    "inspect --format <state format> <container id>",
    "inspect --format <hardening format> <container id>",
]
CLAIM_FENCE_PATHS = {
    "claim": "coordination/application/workflow.py Workflow.claim -> execution_fence.advance (generation + 1, owner)",
    "guard": "coordination/application/execution_fence.py require_current(tx, 'tasks', id, generation, owner) "
             "(the fixture attempt worker's guard; Workflow.complete reaches it through Workflow._owned)",
    "cancel": "coordination/application/messages.py MessageHandler.cancel_in -> execution_fence.advance (generation + 1)",
    "admission": "coordination/application/fleet/admission.py AdmissionControl.reserve_unit / admit_one (refuse "
                 "FleetRefused('paused') from fleet_control.paused)",
    "admission_gap": "MISSING: Workflow.claim (task admission) reads no pause state; only fleet jobs/units are held by "
                     "a paused fleet (DESIGN-D §8 follow-up row)",
}
WATCH = [
    "v2: the org card's `d` is ORG_D, a canonical UUID (the relay refuses `invalid: invalid UUID`); the bridge AUTHs "
    "with the conductor role, so no key is copied",
    "step 2 asserts the conductor and stranger 9000 joins; the owner's own 9000 answer is recorded (it may be `duplicate`)",
    "the first committed disposition is effect_done (revision 1): `received`/`accepted` are implicit, so step 4 asserts "
    "the driver's last receipt is effect_done and the intervention state is done, and records every receipt",
    "step 10's SIGKILL window (inbox row `pending`) is polled at 50 ms: the report says whether it was observed",
    "step 3 counts active ticks from the bridge log; a driver call is ~1 s, so <= 3 ticks is checked as <= 3 + 1",
    "step 6 expects the intervention `state` after resume/pause to be `done` as DESIGN-D §4 says; a different Desktop "
    "reading is reported verbatim",
]


# -- subprocesses: the one chokepoint --------------------------------------------------------------------------------

class Procs:
    """Starts every subprocess in its own process group, records its argv, and kills every group in `finally`."""

    def __init__(self, check_argv):
        self.items = []  # (label, Popen, pgid)
        self.argv_log = []
        self.check_argv = check_argv

    def spawn(self, label, argv, *, env, stdout, stderr, cwd=None, strict=True):
        self.argv_log.append(self.check_argv(label, argv, strict))
        proc = subprocess.Popen(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                start_new_session=True)
        self.items.append((label, proc, proc.pid))
        return proc

    def run(self, label, argv, timeout, *, env=None, cwd=None, strict=True):
        """Foreground: `(returncode, stdout, stderr)`; a timeout kills the whole group."""
        self.argv_log.append(self.check_argv(label, argv, strict))
        proc = subprocess.Popen(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.items.append((label, proc, proc.pid))
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill_group(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise AssertionError(f"{label} timed out after {timeout}s") from None
        return proc.returncode, out, err

    @staticmethod
    def kill_group(pgid, sig):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def kill_all(self):
        for _, proc, pgid in self.items:
            if proc.poll() is None:
                self.kill_group(pgid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        for _, proc, pgid in self.items:
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            self.kill_group(pgid, signal.SIGKILL)  # the whole group: a leader's exit does not end its children
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def residue(self):
        """Labels of the process groups that still have a member."""
        left = []
        for label, _, pgid in self.items:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
            left.append(label)
        return left


class Bridge:
    """One bridge process (`-m codex_harness.entry.processes.buzz_bridge --config ...`), its tick log and its signals."""

    def __init__(self, run, number):
        self.run, self.name = run, f"bridge-{number}"
        self.log, self.err = run.tmp / f"{self.name}.log", run.tmp / f"{self.name}.err"
        self.proc = None

    def start(self):
        argv = [sys.executable, "-B", "-m", "codex_harness.entry.processes.buzz_bridge", "--config",
                str(self.run.bridge_config)]
        with open(self.log, "ab") as out, open(self.err, "ab") as err:
            self.proc = self.run.procs.spawn(self.name, argv, env=self.run.plain_env(), stdout=out, stderr=err,
                                             cwd=str(self.run.tmp))
        self.started = time.monotonic()
        return self

    def ticks(self):
        found = []
        for line in self.log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                tick = json.loads(line)
            except ValueError:
                continue
            if isinstance(tick, dict) and "tick" in tick:
                found.append(tick)
        return found

    def active_ticks(self):
        return [tick for tick in self.ticks() if "inbound" in tick["steps"]]

    def generation(self):
        for tick in reversed(self.ticks()):
            if isinstance(tick["generation"], int):
                return tick["generation"]
        return None

    def signal(self, sig):
        Procs.kill_group(self.proc.pid, sig)

    def wait_exit(self, seconds):
        """The exit code and the seconds the wait took; `AssertionError` when it did not exit in time."""
        began = time.monotonic()
        try:
            code = self.proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"{self.name} did not exit within {seconds}s") from None
        return code, round(time.monotonic() - began, 2)


# -- the run ---------------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, tmp: Path, desktop: Path):
        self.tmp, self.desktop = tmp, desktop
        self.env_file = tmp / "e2e.env"
        self.dsn_file = tmp / "zeus.dsn"
        self.owner_key_file = tmp / "owner.sk"
        self.keys_dir, self.custody_dir = tmp / "keys", tmp / "bridge-keys"
        self.bridge_config, self.driver_config = tmp / "bridge-config.json", tmp / "driver-config.json"
        self.driver_storage = tmp / "driver-storage.json"
        self.owner_keys, self.custody = TestRoleKeys(self.keys_dir), TestRoleKeys(self.custody_dir)
        self.signer = NostrEventSigner(lambda role: self.keys_of(role).pubkey(role),
                                       lambda role, event_id: self.keys_of(role).sign_id(role, event_id))
        self.secrets: set[str] = set()
        self.procs = Procs(self.scan_argv)
        self.relay_port = self.pg_port = 0
        self.url = ""
        self.owned = self.started = False  # preconditions passed / `up` issued
        self.store = None
        self.channels: dict[str, str] = {}
        self.tasks: dict[str, str] = {}
        self.workers: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.bridges: list[Bridge] = []
        self.last_sent: dict[str, float] = {}

    def keys_of(self, role):
        return self.owner_keys if role in OUTSIDE_ROLES else self.custody

    # -- hygiene --------------------------------------------------------------------------------------------------

    def scrub(self, text: str) -> str:
        for value in self.secrets:
            text = text.replace(value, "***")
        return text

    def scan_argv(self, label, argv, strict):
        """Record `argv` (scrubbed); a secret value is never allowed, and a non-docker process also names no credential path."""
        text = " ".join(argv)
        assert not any(value in text for value in self.secrets), f"{label}: a secret value is on the argv"
        paths = (self.keys_dir, self.custody_dir, self.dsn_file, self.owner_key_file, self.env_file)
        if strict:
            assert not any(str(path) in text for path in paths), f"{label}: a credential path is on the argv"
        return {"label": label, "argv": self.scrub(text), "strict": strict}

    def plain_env(self, **extra):
        """A minimal environment: no inherited credential, only PATH/HOME/locale plus the named extras."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", str(self.tmp)),
               "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        env.update(extra)
        return env

    # -- docker ---------------------------------------------------------------------------------------------------

    def docker(self, args, timeout, ok=(0,)):
        try:
            code, out, err = self.procs.run("docker", ["docker", *args], timeout, strict=False)  # inherits the owner's docker env
        except AssertionError as exc:
            raise AssertionError(f"docker {' '.join(args[:2])}: {exc}") from None
        if code not in ok:
            raise AssertionError(f"docker {' '.join(args[7:9] if args[:1] == ['compose'] else args[:2])} exited "
                                 f"{code}: {self.scrub(err or '')[-300:].strip()}")
        return subprocess.CompletedProcess(args, code, out, err)

    def compose(self, *tail, timeout=120, ok=(0,)):
        return self.docker(["compose", "-p", PROJECT, "-f", str(COMPOSE), "--env-file", str(self.env_file), *tail],
                           timeout, ok)

    def container(self, service):
        cid = self.compose("ps", "-q", service, timeout=60).stdout.strip()
        assert cid, f"the {service} container does not exist"
        return cid

    def wait_healthy(self, service, seconds=HEALTH_SECONDS):
        started, state = time.monotonic(), "unknown"
        while time.monotonic() - started < seconds:
            try:
                state = self.docker(["inspect", "--format", STATE_FORMAT, self.container(service)], 30).stdout.strip()
            except AssertionError as exc:
                state = f"inspect failed ({str(exc)[:80]})"
            if state == "running/healthy":
                return round(time.monotonic() - started, 1)
            if state.startswith(("exited", "dead")):
                break
            time.sleep(3)
        if service == "relay":
            self.save_relay_tail()
        raise AssertionError(f"{service} is not healthy after {seconds}s (last state {state})")

    def save_relay_tail(self):
        try:
            logs = self.compose("logs", "--no-color", "--tail", "200", "relay", timeout=60).stdout
        except AssertionError:
            return
        (self.tmp / "relay-tail.log").write_text(self.scrub(logs), encoding="utf-8")

    def residue(self):
        return {
            "containers": self.docker(["ps", "-a", "-q", "--filter", LABEL], 60).stdout.split(),
            "networks": self.docker(["network", "ls", "-q", "--filter", LABEL], 60).stdout.split(),
            "volumes": self.docker(["volume", "ls", "-q", "--filter", LABEL], 60).stdout.split(),
        }

    # -- relay clients (the A4 pattern) ---------------------------------------------------------------------------

    def client(self, role, recv_timeout=30):
        class Verifier:
            def verify(self, event):
                return verify_event(event)

        return BuzzRelayClient(self.url, auth_signer=self.signer, auth_role=role, verifier=Verifier(),
                               max_size=MAX_SIZE, recv_timeout=recv_timeout)

    @contextmanager
    def connected(self, role, **options):
        client = self.client(role, **options)
        try:
            yield client
        finally:
            client.close()

    def send(self, client, role, kind, tags, content=""):
        """Sign, pace (the relay's per-key message limit) and publish; `(event, relay answer)`."""
        wait = self.last_sent.get(role, -1e9) + PACE_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last_sent[role] = time.monotonic()
        event = self.signer.sign(role, {"kind": kind, "created_at": int(time.time()), "tags": tags, "content": content})
        return event, client.publish(event)

    # -- the Zeus store -------------------------------------------------------------------------------------------

    def read(self, fn):
        with self.store.transaction() as tx:
            return fn(tx)

    def task_row(self, label):
        return self.read(lambda tx: tx.get("tasks", self.tasks[label]))

    def transitions(self, command_id):
        return self.read(lambda tx: [row for row in tx.scan(TRANSITIONS) if row["command_id"] == command_id])

    def control(self):
        return self.read(lambda tx: (dict(fleet_state.control(tx)), fleet_state.control_version(tx)))

    def lease_row(self):
        return self.read(lambda tx: tx.get(LEASE_BUCKET, FENCE_ROW))

    def worker_status(self, label):
        path = self.workers[label]["status_file"]
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    # -- the owner driver (the D3 Node driver; one JSON object per op) --------------------------------------------

    def driver(self, op, args=None, timeout=60):
        argv = [NODE, "--import", "./test-loader.mjs", "--experimental-strip-types", DRIVER, op, json.dumps(args or {})]
        env = self.plain_env(ZEUS_E2E_CONFIG=str(self.driver_config), ZEUS_E2E_OWNER_KEY=str(self.owner_key_file),
                             ZEUS_E2E_STORAGE=str(self.driver_storage))
        code, out, err = self.procs.run(f"driver:{op}", argv, timeout, env=env, cwd=str(self.desktop / "desktop"))
        lines = [line for line in out.splitlines() if line.strip()]
        try:
            body = json.loads(lines[-1])
        except (IndexError, ValueError):
            raise AssertionError(f"driver {op} printed no JSON object (exit {code}): "
                                 f"{self.scrub(err or '')[-200:].strip()}") from None
        assert code == 0 and "error" not in body, f"driver {op} failed: {self.scrub(str(body.get('error')))[:300]}"
        return body

    # -- bounded polls --------------------------------------------------------------------------------------------

    @staticmethod
    def poll(fn, seconds, what, every=1.0):
        deadline, last = time.monotonic() + seconds, None
        while True:
            try:
                last = fn()
            except AssertionError as exc:
                last = f"AssertionError: {exc}"
            else:
                if last:
                    return last
            if time.monotonic() >= deadline:
                raise AssertionError(f"timed out after {seconds}s waiting for {what}; last: {str(last)[:300]}")
            time.sleep(every)

    def settle(self, bridge, ticks):
        """Wait until `bridge` has logged `ticks` more tick lines (bounded)."""
        target = len(bridge.ticks()) + ticks
        self.poll(lambda: len(bridge.ticks()) >= target, ticks * TICK + 20, f"{ticks} more ticks of {bridge.name}", 0.5)

    def receipts(self, command_id):
        return self.driver("receipts", {"commandId": command_id})["receipts"]

    def wait_effect(self, command_id, disposition="effect_done"):
        """The driver's receipts of `command_id` once one has `disposition`, within 60 s."""
        def seen():
            found = self.receipts(command_id)
            return found if any(r["disposition"] == disposition for r in found) else None
        return self.poll(seen, COMMAND_WAIT, f"a {disposition} receipt of {command_id}", 2.0)

    def wait_state(self, args, wanted="done"):
        def reached():
            result = self.driver("state", args)
            return result if result["state"] == wanted else None
        return self.poll(reached, COMMAND_WAIT, f"state {wanted} of {args}", 2.0)

    def wait_actionable(self, args):
        return self.poll(lambda: (r := self.driver("state", args))["actionable"] and r, COMMAND_WAIT,
                         f"{args} to be actionable", 2.0)

    def start_bridge(self):
        bridge = Bridge(self, len(self.bridges) + 1).start()
        self.bridges.append(bridge)
        return bridge

    def wait_leader(self, bridge, extra=0):
        """Wait until `bridge` holds the lease (a numeric generation in its tick log); the old lease expires first."""
        return self.poll(bridge.generation, LEASE_TTL + 3 * TICK + 20 + extra, f"{bridge.name} to hold the lease", 0.5)


# -- the report ------------------------------------------------------------------------------------------------------

class Report:
    def __init__(self, run, path):
        self.run, self.path, self.steps, self.failed, self.refused, self.aborted = run, path, [], [], False, False
        self.save()

    def save(self):
        body = {"project": PROJECT, "relay_url": self.run.url, "docker_forms": ["docker " + f for f in DOCKER_FORMS],
                "claim_fence_paths": CLAIM_FENCE_PATHS, "watch": WATCH, "tasks": self.run.tasks,
                "argv": self.run.procs.argv_log, "steps": self.steps}
        self.path.write_text(self.run.scrub(json.dumps(body, indent=2, default=str)), encoding="utf-8")

    def step(self, name, asserts, fn, *, fatal=False):
        record = {"step": name, "asserts": asserts, "records": {}}
        self.steps.append(record)
        if self.aborted:
            record["status"], record["why"] = "skipped", "an earlier fatal step failed"
            self.save()
            return False
        began = time.monotonic()
        try:
            fn(record["records"])
            record["status"] = "pass"
        except Exception as exc:  # noqa: BLE001 - the run names the step and goes on
            record["status"] = "REFUSED" if isinstance(exc, Refusal) else "FAIL"
            record["error"] = self.run.scrub(f"{type(exc).__name__}: {exc}")[:800]
            self.refused = self.refused or isinstance(exc, Refusal)
            self.failed.append(name)
            self.aborted = self.aborted or fatal
        record["seconds"] = round(time.monotonic() - began, 1)
        self.save()
        return record["status"] == "pass"


def compose_services():
    """The service names of compose.yaml: the two-space-indented keys under the top-level `services:`."""
    names, inside = [], False
    for line in COMPOSE.read_text(encoding="utf-8").splitlines():
        if line.startswith("services:"):
            inside = True
        elif inside and line and not line.startswith((" ", "#")):
            break
        elif inside and line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":") \
                and not line.strip().startswith("#"):
            names.append(line.strip()[:-1])
    assert names, "no service found in compose.yaml"
    return names


# -- steps -----------------------------------------------------------------------------------------------------------

def step_preconditions(run, rec):
    if not shutil.which("docker"):
        raise Refusal("docker is not on PATH")
    if not Path(NODE).exists():
        raise Refusal("the pinned node binary does not exist")
    if not (run.desktop / "desktop" / DRIVER).is_file():
        raise Refusal("the D3 owner driver is missing in --desktop")
    text = COMPOSE.read_text(encoding="utf-8")
    if "__DIGEST_TBD__" in text:
        raise Refusal("a placeholder digest is in the compose file")
    residue = run.residue()
    rec["residue_before"] = {key: len(value) for key, value in residue.items()}
    if any(residue.values()):
        raise Refusal(f"a resource of project {PROJECT} already exists; it is foreign to this run and is never cleaned")
    assert str(run.tmp).startswith(str(SCRATCH.resolve()) + "/") and not str(run.tmp).startswith("/tmp"), "the work dir is not scratch"
    run.relay_port, run.pg_port = free_port(), free_port()
    assert run.relay_port != run.pg_port, "the loopback ports collide"
    run.url = f"ws://127.0.0.1:{run.relay_port}"
    rec.update(relay_port=run.relay_port, zeus_postgres_port=run.pg_port, workdir=str(run.tmp), services=compose_services())
    run.owned = True


def write_secret(path: Path, text: str):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    assert path.stat().st_mode & 0o777 == 0o600, f"{path.name} is not mode 0600"


def make_keys(run, rec, organization):
    """Owner/stranger/relay keys outside the bridge's custody; conductor (the bridge's NIP-42 and signing identity, DESIGN §6.2.1) and every org role inside it."""
    for role in OUTSIDE_ROLES:
        run.owner_keys.create(role)
    names = ["conductor"] + [custody_name(role_id) for role_id in organization.agents if role_id != "conductor"]
    for name in dict.fromkeys(names):
        run.custody.create(name)
    owner_hex = (run.keys_dir / "owner.key").read_bytes().hex()  # the file is the run's own throwaway key
    write_secret(run.owner_key_file, owner_hex + "\n")
    run.secrets.add(owner_hex)
    pubkeys = {role: run.keys_of(role).pubkey(role) for role in ("owner", "stranger", "conductor")}
    assert len(set(pubkeys.values())) == 3, "the role keys are not distinct"
    rec["pubkeys"] = pubkeys
    rec["custody_names"] = {role_id: custody_name(role_id) for role_id in organization.agents}
    return pubkeys


def write_env(run, pubkeys):
    relay_secret = (run.keys_dir / "relay.key").read_bytes().hex()
    values = {
        "RELAY_OWNER_PUBKEY": pubkeys["owner"],
        "BUZZ_RELAY_PRIVATE_KEY": relay_secret,
        "BUZZ_GIT_HOOK_HMAC_SECRET": secrets.token_hex(32),
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "REDIS_PASSWORD": secrets.token_hex(16),
        "BUZZ_S3_ACCESS_KEY": "k" + secrets.token_hex(8),
        "BUZZ_S3_SECRET_KEY": secrets.token_hex(16),
        "ZEUS_E2E_PG_PASSWORD": secrets.token_hex(16),
        "ZEUS_E2E_PG_PORT": str(run.pg_port),
        "BUZZ_E2E_PORT": str(run.relay_port),
        "BUZZ_E2E_ENV_FILE": str(run.env_file),
    }
    public = ("ZEUS_E2E_PG_PORT", "BUZZ_E2E_PORT", "BUZZ_E2E_ENV_FILE", "RELAY_OWNER_PUBKEY")
    run.secrets.update(value for key, value in values.items() if key not in public)
    write_secret(run.env_file, "".join(f"{key}={value}\n" for key, value in values.items()))
    password = values["ZEUS_E2E_PG_PASSWORD"]
    dsn_text = f"{SCHEME}zeus:{password}@127.0.0.1:{run.pg_port}/zeus"
    run.secrets.add(dsn_text)
    write_secret(run.dsn_file, dsn_text + "\n")
    return dsn_text


def check_hardening(run, rec):
    services = compose_services()
    containers = run.compose("ps", "-a", "-q", timeout=60).stdout.split()
    assert len(containers) == len(services), f"{len(containers)} containers for the services {services}"
    published = {}
    for cid in containers:
        name, privileged, mode, ports, cap_add, mounts = run.docker(["inspect", "--format", HARDENING_FORMAT, cid],
                                                                    30).stdout.strip().split("|", 5)
        bindings = json.loads(ports) or {}
        host_ips = sorted({b["HostIp"] for binds in bindings.values() for b in binds or []})
        published[name.lstrip("/")] = {"privileged": privileged, "network_mode": mode, "host_ips": host_ips,
                                       "cap_add": json.loads(cap_add), "binding_count": len(bindings)}
        assert privileged == "false", f"{name} runs privileged"
        assert mode != "host", f"{name} uses the host network"
        assert not json.loads(cap_add), f"{name} adds capabilities"
        assert "docker.sock" not in mounts, f"{name} mounts the docker socket"
        assert set(host_ips) <= {"127.0.0.1"}, f"{name} publishes on {host_ips}"
    rec["containers"] = published
    for service in services:  # compose names: <project>-<service>-<n> (v2) or <project>_<service>_<n> (v1)
        found = [key for key in published if key.startswith((f"{PROJECT}-{service}-", f"{PROJECT}_{service}_"))]
        assert len(found) == 1, f"service {service} has {len(found)} containers: {sorted(published)}"
    for service in ("relay", "zeus-postgres"):
        mine = next(v for k, v in published.items() if k.startswith((f"{PROJECT}-{service}-", f"{PROJECT}_{service}_")))
        assert mine["host_ips"] == ["127.0.0.1"], f"{service} publishes no loopback port"


def fleet_config(run):
    lanes = [{"id": lane, "team": team, "repository": str(run.tmp / "fleet" / f"repo-{lane}"), "schema": f"lane_{lane}",
              "redis_namespace": f"fleet-{lane}", "runtime": str(run.tmp / "fleet" / f"rt-{lane}")}
             for lane, team in (("a", "alpha"), ("b", "beta"))]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-e2e", "max_parallel": 2, "budget": {"per_host": 4, "total": 8},
            "lanes": lanes}


def seed_fixture_zeus(run, rec, store=None):
    """Migrate (unless an injected store is given), register the fleet, submit t1-t3 and claim t2 and t3."""
    store = store or run.store
    organization = fz.load_organization(ORGANIZATION)
    counts = {"conductor": 0, "lead": 0, "worker": 0}
    for agent in organization.agents.values():
        counts[agent.role] += 1
    assert counts == {"conductor": 1, "lead": 2, "worker": 3}, counts
    FleetRegistry(store).register(fleet_config(run))
    workflow = fz.build_workflow(store, organization)
    for label, sender, recipient in TASKS:
        message = envelope("task.assign", sender, recipient, "implement",
                           {"objective": "e2e fixture", "title": f"e2e {label}"}, "zeus-buzz-e2e")
        run.tasks[label] = workflow.submit(message)["id"]
    claims = {}
    for label, agent in (("t2", "worker:alpha-2"), ("t3", "worker:beta-1")):  # Workflow.claim: the fence advances
        owner = f"e2e-fixture-{label}"
        row = workflow.claim(agent, owner, lease_seconds=3600)
        assert row is not None and row["id"] == run.tasks[label], f"{label} was not claimed"
        assert row["generation"] == 1 and row["lease_owner"] == owner and row["status"] == "running"
        claims[label] = {"generation": row["generation"], "owner": owner, "lease_until": row["lease_until"]}
    with store.transaction() as tx:
        for label, claim in claims.items():
            fence = execution_fence.current(tx, "tasks", run.tasks[label])
            assert fence["generation"] == claim["generation"] and fence["owner"] == claim["owner"]
        assert tx.get("tasks", run.tasks["t1"])["status"] == "queued"
        assert fleet_state.control(tx)["paused"] is False
    rec["fixture"] = {"organization": counts, "tasks": run.tasks, "claims": claims, "fleet": "fleet-e2e"}
    return claims


def bootstrap_relay(run, rec, pubkeys):
    """Owner AUTH, then 9030 (conductor, stranger), then the private channels via 9007 with 9000 joins (the A4 pattern)."""
    answers = {}
    with run.connected("owner") as owner:
        for role in ("conductor", "stranger"):
            _, answers[f"9030_{role}"] = run.send(owner, "owner", 9030, [["p", pubkeys[role]]])
            assert answers[f"9030_{role}"]["accepted"] is True, f"kind 9030 ({role}) was not accepted"
        for name in CHANNELS:
            chan = str(uuid.uuid4())
            tags = [["h", chan], ["name", f"zeus-e2e-{name}"], ["visibility", "private"], ["channel_type", "stream"]]
            _, answers[f"9007_{name}"] = run.send(owner, "owner", 9007, tags)
            assert answers[f"9007_{name}"]["accepted"] is True, f"kind 9007 ({name}) was not accepted"
            run.channels[name] = chan
            _, answers[f"9000_{name}_conductor"] = run.send(owner, "owner", 9000, [["h", chan], ["p", pubkeys["conductor"]]])
            assert answers[f"9000_{name}_conductor"]["accepted"] is True, f"9000 conductor -> {name} refused"
            _, answers[f"9000_{name}_owner"] = run.send(owner, "owner", 9000, [["h", chan], ["p", pubkeys["owner"]]])
        _, answers["9000_commander_stranger"] = run.send(owner, "owner", 9000,
                                                         [["h", run.channels["commander"]], ["p", pubkeys["stranger"]]])
        assert answers["9000_commander_stranger"]["accepted"] is True, "9000 stranger -> commander refused"
    rec["relay_answers"] = answers
    rec["channels"] = run.channels


def write_configs(run, pubkeys):
    channels = [run.channels[name] for name in CHANNELS]
    bridge = {"relay_url": run.url, "channels": channels, "owners": [pubkeys["owner"]], "custody_dir": str(run.custody_dir),
              "store_dsn_file": str(run.dsn_file), "commander_channel": run.channels["commander"], "org_d": ORG_D,
              "team_channels": {team: run.channels[team] for team in TEAMS}, "organization_file": str(ORGANIZATION),
              "tick_seconds": TICK, "lease_ttl_seconds": LEASE_TTL, "recv_timeout": RECV_TIMEOUT, "max_seconds": 3000}
    run.bridge_config.write_text(json.dumps(bridge, indent=2), encoding="utf-8")
    driver = {"conductorPubkey": pubkeys["conductor"], "orgD": ORG_D, "commanderChannelId": run.channels["commander"],
              "teamChannelIds": [run.channels[team] for team in TEAMS], "relay_url": run.url}
    run.driver_config.write_text(json.dumps(driver, indent=2), encoding="utf-8")


def start_attempt_worker(run, label, *, complete_on=None):
    claim = run.claims[label]
    status_file = run.tmp / f"worker-{label}.status.json"
    argv = [sys.executable, "-B", str(WORKER), "--task", run.tasks[label], "--generation", str(claim["generation"]),
            "--owner", claim["owner"], "--organization", str(ORGANIZATION), "--status-file", str(status_file)]
    if complete_on is not None:
        argv += ["--complete-on", str(complete_on)]
    with open(run.tmp / f"worker-{label}.log", "ab") as out:
        proc = run.procs.spawn(f"worker-{label}", argv, env=run.plain_env(ZEUS_E2E_DSN_FILE=str(run.dsn_file)),
                               stdout=out, stderr=subprocess.STDOUT, cwd=str(run.tmp))
    run.workers[label] = {"proc": proc, "status_file": status_file, "complete_on": complete_on}
    run.poll(lambda: run.worker_status(label).get("fence_ok", 0) >= 1, 60, f"worker {label} to hold its fence", 0.5)


def step_stack(run, rec):
    organization = fz.load_organization(ORGANIZATION)
    pubkeys = make_keys(run, rec, organization)
    dsn_text = write_env(run, pubkeys)
    rec["env_file_mode"] = "0600"
    run.started = True
    run.compose("up", "-d", timeout=900)
    rec["relay_healthy_after_seconds"] = run.wait_healthy("relay")
    rec["zeus_postgres_healthy_after_seconds"] = run.wait_healthy("zeus-postgres", 120)
    check_hardening(run, rec)
    run.store = PostgresStore(dsn_text)
    rec["migrate"] = run.store.migrate()
    run.claims = seed_fixture_zeus(run, rec)
    bootstrap_relay(run, rec, pubkeys)
    write_configs(run, pubkeys)
    start_attempt_worker(run, "t2")
    start_attempt_worker(run, "t3", complete_on=run.tmp / "t3.complete")
    rec["workers"] = {label: run.worker_status(label) for label in ("t2", "t3")}


def step_org(run, rec):
    bridge = run.start_bridge()
    rec["bridge_argv"] = "python -B -m codex_harness.entry.processes.buzz_bridge --config <bridge-config.json>"
    org = run.poll(lambda: (r := run.driver("org"))["status"] == "verified" and r, 3 * TICK + 30, "a verified org card", 1.0)
    ticks = len(bridge.active_ticks())
    rec["org"], rec["active_ticks_when_verified"] = org, ticks
    assert (org["conductor"], org["leads"], org["workers"]) == (1, 2, 3), f"org counts {org}"
    assert ticks <= 3 + 1, f"the org card needed {ticks} active ticks"
    cards = {}
    for label in ("t1", "t2", "t3"):
        cards[label] = run.poll(lambda label=label: (r := run.driver("card", {"task": run.tasks[label]}))["verified"] and r,
                                3 * TICK + 20, f"a verified card of {label}", 1.0)
        assert cards[label]["rootEventId"], f"card {label} has no task root"
    rec["cards"] = cards
    assert cards["t1"]["status"] == "queued" and cards["t2"]["status"] == "running", cards


def settle_unchanged(run, bridge, rec, key, before, read):
    run.settle(bridge, 3)
    after = read()
    rec[key] = {"before": before, "after": after}
    assert after == before, f"{key} changed: {before} -> {after}"


def step_cancel_queued(run, rec):
    bridge = run.bridges[0]
    t1 = run.tasks["t1"]
    card = run.driver("card", {"task": t1})
    assert card["generation"] == 0, card
    sent = run.driver("send", {"op": "cancel_task", "task": t1, "reason": "e2e cancel of the queued task"})
    assert sent["accepted"] is True, f"the relay refused the command: {sent}"
    command_id, event_id = sent["commandId"], sent["eventId"]
    rec["sent"] = sent
    receipts = run.wait_effect(command_id)
    rec["receipts"] = receipts
    assert receipts[-1]["disposition"] == "effect_done", receipts
    assert [r["revision"] for r in receipts] == sorted({r["revision"] for r in receipts}), receipts
    rec["state"] = run.wait_state({"op": "cancel_task", "task": t1})
    transitions = run.transitions(command_id)
    row = run.task_row("t1")
    rec["store"] = {"transitions": [(r["transition_revision"], r["disposition"]) for r in transitions],
                    "status": row["status"], "generation": row["generation"]}
    assert [(r["disposition"], r["generation_after"]) for r in transitions] == [("effect_done", 1)], transitions
    assert (row["status"], row["generation"]) == ("cancelled", 1), rec["store"]
    run.settle(bridge, 2)
    notices = run.read(lambda tx: len([r for r in tx.scan("outbox") if t1 in json.dumps(r.get("message", {}))]))
    again = run.driver("send", {"republish": event_id})
    rec["republish"] = again
    assert again["accepted"] is True and again["message"].startswith("duplicate:"), f"republish answer {again}"
    run.settle(bridge, 3)
    row_after, transitions_after = run.task_row("t1"), run.transitions(command_id)
    notices_after = run.read(lambda tx: len([r for r in tx.scan("outbox") if t1 in json.dumps(r.get("message", {}))]))
    rec["effects"] = {"transitions": len(transitions_after), "generation": row_after["generation"],
                      "notice_rows_before": notices, "notice_rows_after": notices_after}
    assert len(transitions_after) == 1 and row_after["generation"] == 1, "a second effect appeared"
    assert notices_after == notices, "the republished command wrote another notice"
    command = run.read(lambda tx: tx.get(COMMANDS, command_id))
    assert command["aliases"] == [] and command["conflicts"] == [], command


def step_cancel_running(run, rec):
    t2, claim = run.tasks["t2"], run.claims["t2"]
    before = run.worker_status("t2")
    assert before["fence_ok"] >= 1 and before["fence_lost"] is False, before
    sent = run.driver("send", {"op": "cancel_task", "task": t2, "reason": "e2e cancel of the running task"})
    assert sent["accepted"] is True, f"the relay refused the command: {sent}"
    rec["sent"] = sent
    rec["receipts"] = run.wait_effect(sent["commandId"])
    row = run.task_row("t2")
    fence = run.read(lambda tx: execution_fence.current(tx, "tasks", t2))
    rec["store"] = {"status": row["status"], "generation": row["generation"], "fence_generation": fence["generation"]}
    assert row["status"] == "cancelled" and row["generation"] == claim["generation"] + 1, rec["store"]
    assert fence["generation"] == claim["generation"] + 1, "the fence did not advance"
    lost = run.poll(lambda: (s := run.worker_status("t2"))["fence_lost"] and s, 30, "the fixture attempt to lose its fence", 1.0)
    rec["worker"] = {"before": before, "after": lost}
    assert lost["completed"] is False, "the cancelled task's holder completed it"
    rec["card"] = run.poll(lambda: (c := run.driver("card", {"task": t2}))["status"] == "cancelled" and c, 3 * TICK + 40,
                           "the t2 card to show cancelled", 2.0)
    assert rec["card"]["verified"] is True and rec["card"]["generation"] == claim["generation"] + 1, rec["card"]


def probe_admission(run):
    """The fleet admission check (`AdmissionControl.reserve_unit`): `(refusal code or None, cached flag)`."""
    try:
        reserved = AdmissionControl(run.store).reserve_unit(PROBE_UNIT, "conductor", "a", "zeus-buzz-e2e admission probe")
    except FleetRefused as refused:
        return refused.reason_code, None
    return None, reserved["cached"]


def step_pause_resume(run, rec):
    version0 = run.control()[1]
    work = run.worker_status("t3")
    run.wait_actionable({"op": "pause_fleet"})
    paused = run.driver("send", {"op": "pause_fleet", "reason": "e2e pause"})
    assert paused["accepted"] is True, paused
    rec["pause_receipts"] = run.wait_effect(paused["commandId"])
    rec["pause_state"] = run.wait_state({"op": "pause_fleet"})
    control, version = run.control()
    assert control["paused"] is True and version == version0 + 1, (control, version)
    code, _ = probe_admission(run)
    rec["admission_while_paused"] = code
    assert code == "paused", f"fleet admission did not refuse with paused: {code}"
    time.sleep(3)
    t3, work_after = run.task_row("t3"), run.worker_status("t3")
    rec["running_work"] = {"status": t3["status"], "attempts_before": work["attempts"], "attempts_after": work_after["attempts"]}
    assert t3["status"] == "running" and work_after["fence_lost"] is False and work_after["attempts"] > work["attempts"], \
        rec["running_work"]
    rec["resume_offered"] = run.wait_actionable({"op": "resume_fleet"})
    resumed = run.driver("send", {"op": "resume_fleet", "reason": "e2e resume"})
    assert resumed["accepted"] is True, resumed
    rec["resume_receipts"] = run.wait_effect(resumed["commandId"])
    rec["resume_state"] = run.wait_state({"op": "resume_fleet"})
    control, version = run.control()
    assert control["paused"] is False and version == version0 + 2, (control, version)
    code, cached = probe_admission(run)
    rec["admission_after_resume"] = {"refusal": code, "cached": cached}
    assert code is None and cached is False, "fleet admission did not open after resume"
    rec["missing_admission_row"] = CLAIM_FENCE_PATHS["admission_gap"]


def step_desk(run, rec):
    before = run.read(lambda tx: (tx.scan("tasks"), fleet_state.control(tx)))
    sent = run.driver("send", {"op": "desk_turn", "text": "e2e desk turn"})
    assert sent["accepted"] is True, sent
    rec["sent"] = sent
    rec["receipts"] = run.wait_effect(sent["commandId"], "refused")
    [transition] = run.transitions(sent["commandId"])
    rec["transition"] = {"disposition": transition["disposition"], "reason_code": transition["reason_code"]}
    assert (transition["disposition"], transition["reason_code"]) == ("refused", "desk_not_migrated"), rec["transition"]
    run.settle(run.bridges[0], 2)
    assert run.read(lambda tx: (tx.scan("tasks"), fleet_state.control(tx))) == before, "a desk turn changed Zeus state"


def forged_command(run, op, version):
    command = {"schema": "urn:zeus:buzz-command:1", "command_id": str(uuid.uuid4()), "op": op, "task_id": None,
               "expected_generation": None, "expected_control": {"paused": False, "version": version},
               "reason": "forged e2e command", "desk": None, "issued_at": datetime.now(UTC).isoformat()}
    return command, "```zeus:command\n" + json.dumps(command) + "\n```"


def step_forged(run, rec):
    bridge = run.bridges[0]
    control0, version0 = run.control()
    commands = {}
    for role in ("stranger", "conductor"):  # a relay member off the owner allowlist, and a role key (the bridge's own)
        command, content = forged_command(run, "pause_fleet", version0)
        with run.connected(role) as client:
            _, answer = run.send(client, role, 9, [["h", run.channels["commander"]]], content)
        assert answer["accepted"] is True, f"the relay refused the {role}-signed command: {answer}"
        commands[role] = {"command_id": command["command_id"], "answer": answer}
    rec["published"] = commands
    run.settle(bridge, 4)
    for role, info in commands.items():
        assert run.read(lambda tx, c=info["command_id"]: tx.get(COMMANDS, c)) is None, f"the {role}-signed command was bound"
        assert run.transitions(info["command_id"]) == [], f"the {role}-signed command has a transition"
    control, version = run.control()
    assert (control["paused"], version) == (control0["paused"], version0), "a forged command changed the fleet"
    rec["receipts"] = {role: run.receipts(info["command_id"]) for role, info in commands.items()}  # observed, not assumed
    assert all(found == [] for found in rec["receipts"].values()), f"a forged command got a receipt: {rec['receipts']}"


def stop_bridge(run, bridge, rec, key):
    bridge.signal(signal.SIGTERM)
    code, seconds = bridge.wait_exit(STOP_BOUND + 5)
    rec[key] = {"exit": code, "seconds": seconds, "bound": STOP_BOUND}
    assert code == 0, f"{bridge.name} exited {code}"
    assert seconds <= STOP_BOUND, f"{bridge.name} took {seconds}s to stop (bound {STOP_BOUND}s)"


def step_sigterm(run, rec):
    first = run.bridges[0]
    generation1 = first.generation()
    version0 = run.control()[1]
    run.wait_actionable({"op": "pause_fleet"})  # armed from the live org snapshot, before the bridge goes down
    run.settle(first, 1)  # between ticks: the last line was just written
    stop_bridge(run, first, rec, "stop_between_ticks")
    Path(run.tmp / "t3.complete").write_text("go", encoding="utf-8")  # the fixture work finishes with the bridge down
    done = run.poll(lambda: (s := run.worker_status("t3"))["completed"] and s, 60, "t3's terminal write", 1.0)
    t3 = run.task_row("t3")
    rec["fixture_work"] = {"worker": done, "task_status": t3["status"]}
    assert t3["status"] == "succeeded", t3["status"]
    sent = run.driver("send", {"op": "pause_fleet", "reason": "e2e pause published while the bridge is down"})
    assert sent["accepted"] is True, sent
    rec["published_while_down"] = sent
    second = run.start_bridge()
    generation2 = run.wait_leader(second)
    rec["generations"] = {"first": generation1, "second": generation2}
    assert generation2 > generation1, "the restart did not advance the generation"
    rec["receipts"] = run.wait_effect(sent["commandId"])
    control, version = run.control()
    assert control["paused"] is True and version == version0 + 1, (control, version)
    assert len(run.transitions(sent["commandId"])) == 1, "the cursor replay produced a second effect"
    # mid-pass (best effort): the stop arrives just after the next tick began (one tick after the last line)
    last = len(second.ticks())
    run.poll(lambda: len(second.ticks()) > last, TICK + 10, "a tick of the second bridge", 0.1)
    time.sleep(TICK + 0.15)
    before = len(second.ticks())
    stop_bridge(run, second, rec, "stop_mid_pass")
    # a tick line written AFTER the signal means a tick was in flight: its step keys show how far the pass got
    rec["mid_pass_ticks_after_signal"] = [sorted(t["steps"]) for t in second.ticks()[before:]]
    third = run.start_bridge()
    run.wait_leader(third)


def current_leader(run):
    """The newest bridge: alive, and holding the lease (a failed step 9 must not leave steps 10/11 on the wrong process)."""
    bridge = run.bridges[-1]
    assert bridge.proc.poll() is None, f"{bridge.name} is not running"
    assert bridge.generation() == run.lease_row()["generation"], f"{bridge.name} does not hold the lease"
    assert sum(1 for b in run.bridges if b.proc.poll() is None) == 1, "more than one bridge is running"
    return bridge


def step_sigkill(run, rec):
    bridge = current_leader(run)
    version0 = run.control()[1]
    run.wait_actionable({"op": "resume_fleet"})
    sent = run.driver("send", {"op": "resume_fleet", "reason": "e2e resume interrupted by SIGKILL"})
    assert sent["accepted"] is True, sent
    command_id, event_id = sent["commandId"], sent["eventId"]
    seen = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and seen is None:  # the inbox row of the command event, then SIGKILL at once
        row = run.read(lambda tx: tx.get("remote_inbox", event_id))
        seen = None if row is None else row["state"]
        if seen is None:
            time.sleep(0.05)
    bridge.signal(signal.SIGKILL)
    code, _ = bridge.wait_exit(15)
    rec["killed"] = {"inbox_state_at_kill": seen, "pending_window_observed": seen == "pending", "exit": code}
    assert seen is not None, "the command's inbox row never appeared"
    assert code == -signal.SIGKILL, f"the bridge exit code was {code}"
    restarted = run.start_bridge()
    rec["generation_after_restart"] = run.wait_leader(restarted)
    rec["receipts"] = run.wait_effect(command_id)
    run.settle(restarted, 3)
    control, version = run.control()
    assert control["paused"] is False and version == version0 + 1, (control, version)
    transitions = run.transitions(command_id)
    rec["store"] = {"transitions": [(r["transition_revision"], r["disposition"]) for r in transitions]}
    assert [r["disposition"] for r in transitions] == ["effect_done"], transitions
    receipts = run.receipts(command_id)
    rec["receipts_after_settle"] = receipts
    assert [r["disposition"] for r in receipts] == ["effect_done"], f"exactly one receipt expected: {receipts}"


def step_passive(run, rec):
    holder = current_leader(run)
    lease = run.lease_row()
    inbox0 = run.read(lambda tx: len(tx.scan("remote_inbox")))
    holder_ticks0 = len(holder.ticks())
    second = run.start_bridge()
    run.poll(lambda: len(second.ticks()) >= 3, 3 * TICK + 30, "three ticks of the second bridge", 0.5)
    ticks = second.ticks()
    rec["passive_ticks"] = [{"tick": t["tick"], "generation": t["generation"], "steps": t["steps"]} for t in ticks]
    assert all(t["steps"] == {"lease": "held_by_other"} and t["generation"] == "passive" for t in ticks), rec["passive_ticks"]
    lease_after = run.lease_row()
    rec["lease"] = {"owner_unchanged": lease["owner"] == lease_after["owner"],
                    "generation": (lease["generation"], lease_after["generation"])}
    assert (lease["owner"], lease["generation"]) == (lease_after["owner"], lease_after["generation"]), \
        "the passive bridge took or advanced the lease"
    assert run.read(lambda tx: len(tx.scan("remote_inbox"))) == inbox0, "the passive bridge committed an inbox row"
    assert len(holder.ticks()) > holder_ticks0 and holder.generation() == lease["generation"], "the holder stopped"
    stop_bridge(run, second, rec, "passive_stop")


def step_cleanup(run, rec):
    """Kill every group, `down -v`, and check the residue (containers, networks, volumes, processes)."""
    run.procs.kill_all()
    rec["processes_left"] = run.procs.residue()
    assert not rec["processes_left"], f"process groups remain: {rec['processes_left']}"
    run.compose("down", "-v", "--remove-orphans", timeout=300)
    residue = run.residue()
    rec["residue_after"] = {key: len(value) for key, value in residue.items()}
    assert not any(residue.values()), f"resources remain after down -v: {rec['residue_after']}"
    remove_secrets(run)
    rec["secrets_removed"] = True


def remove_secrets(run):
    """Delete the keys, the DSN, the env file and the owner-key file of the work dir (0600 until now)."""
    for directory in (run.keys_dir, run.custody_dir):
        shutil.rmtree(directory, ignore_errors=True)
    for path in (run.env_file, run.dsn_file, run.owner_key_file):
        path.unlink(missing_ok=True)
    left = [str(p) for p in (run.keys_dir, run.custody_dir, run.env_file, run.dsn_file, run.owner_key_file) if p.exists()]
    assert not left, f"secrets remain: {left}"


# -- the run ---------------------------------------------------------------------------------------------------------

def run_all(tmp, report_path, keep_on_failure, desktop):
    run = Run(tmp, desktop)
    report = Report(run, report_path)
    print("docker argv forms used by this runner (the R-P guard is not involved):", flush=True)
    for form in DOCKER_FORMS:
        print(f"  docker {form}", flush=True)
    try:
        report.step("1 preconditions", "docker, node and the driver exist; digests pinned; no foreign residue; free ports",
                    lambda rec: step_preconditions(run, rec), fatal=True)
        report.step("2 stack + fixture Zeus", "keys 0600; relay and zeus-postgres healthy; hardening; seed; relay bootstrap",
                    lambda rec: step_stack(run, rec), fatal=True)
        report.step("3 N1,N2", "org verified 1/2/3 within <= 3 ticks; cards t1/t2 verified with their roots",
                    lambda rec: step_org(run, rec), fatal=True)
        report.step("4 N3,N4", "cancel t1: effect_done, state done, one effect; republish -> duplicate, no second effect",
                    lambda rec: step_cancel_queued(run, rec))
        report.step("5 T2", "cancel t2: generation advances, the fixture attempt is fence-refused, the card is cancelled",
                    lambda rec: step_cancel_running(run, rec))
        report.step("6 T3", "pause: done, admission refuses paused, running work continues; resume: done, admission opens",
                    lambda rec: step_pause_resume(run, rec))
        report.step("7 N4 desk", "desk_turn -> refused desk_not_migrated; nothing else changed",
                    lambda rec: step_desk(run, rec))
        report.step("8 S1/F1", "stranger- and role-signed command fences: no effect, no transition, no receipt",
                    lambda rec: step_forged(run, rec))
        report.step("9 C2", "SIGTERM: exit 0 within recv_timeout + one step; work completes; cursor replay after restart",
                    lambda rec: step_sigterm(run, rec))
        report.step("10 R3", "SIGKILL after the inbox commit: after the restart exactly one effect and one receipt",
                    lambda rec: step_sigkill(run, rec))
        report.step("11 R4", "a second bridge stays passive while the first holds the lease",
                    lambda rec: step_passive(run, rec))
    finally:
        run.procs.kill_all()  # every child process group, whatever happened (step 12 re-checks the residue)
        if run.owned and run.started and report.failed and keep_on_failure:
            print(f"--keep-on-failure: the stack is left running; remove it with: docker compose -p {PROJECT} "
                  f"-f {COMPOSE} --env-file {run.env_file} down -v --remove-orphans", flush=True)
        elif run.owned and run.started:
            report.aborted = False
            report.step("12 C4", "kill every group; down -v; zero containers, networks, volumes, processes; secrets removed",
                        lambda rec: step_cleanup(run, rec))
        else:
            remove_secrets_quietly(run)
        report.save()
        print(f"BUZZ_D2_REPORT={report.path}", flush=True)
    if report.refused:
        print(f"REFUSED: {report.steps[0].get('error', '')}", flush=True)
        return 2
    if report.failed:
        print(f"FAILED steps: {report.failed}", flush=True)
        return 1
    print("all asserted steps passed", flush=True)
    return 0


def remove_secrets_quietly(run):
    try:
        remove_secrets(run)
    except AssertionError:
        pass


# -- D4: the static lint of the production templates (DESIGN-D section 5; no Docker, no systemd, no host effect) ---------

TEMPLATES = HERE.parents[2] / "deploy"
BRIDGE_UNIT = Path("buzz-bridge/buzz-bridge.service.template")
BRIDGE_CONFIG = Path("buzz-bridge/config.template.json")
RELAY_COMPOSE = Path("buzz-relay/compose.template.yaml")
yaml_nodes = yaml.compose  # a bare name: the D2 static test reads every `.compose(` attribute call as a docker form
PLACEHOLDER = re.compile(r"@[A-Z][A-Z0-9_]*@")
INTERPOLATION = re.compile(r"\$\{[^}]*\}")
SECRET_KEY = re.compile(r"password|passwd|secret|token|private|nsec|api_?key|access_?key|hmac|credential", re.I)
PATH_KEY = re.compile(r"_(file|path|dir)$", re.I)
SECRET_VALUES = ((re.compile(r"\bnsec1[0-9a-z]{8,}"), "an nsec key"),
                 (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "an sk- key"),
                 (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "credentials inside a URL"))
BOOLEAN_WORDS = frozenset({"true", "false", "yes", "no", "on", "off", "0", "1"})
LOOPBACK_PREFIXES = ("127.0.0.1:", "[::1]:", "localhost:")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
TIME_UNITS = {"us": 1e-6, "usec": 1e-6, "ms": 1e-3, "msec": 1e-3, "s": 1, "sec": 1, "second": 1, "seconds": 1, "m": 60,
              "min": 60, "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "": 1}


def template_secret_literal(key, value):
    """Why `value` under `key` is a literal secret, or None (a placeholder, an interpolation, a flag or a path is fine)."""
    text = INTERPOLATION.sub("", PLACEHOLDER.sub("", str(value))).strip()
    for pattern, what in SECRET_VALUES:
        if pattern.search(INTERPOLATION.sub("", PLACEHOLDER.sub("PH", str(value)))):
            return f"{what} in a literal value"
    if SECRET_KEY.search(key) and not PATH_KEY.search(key) and text and text.lower() not in BOOLEAN_WORDS:
        return f"a literal value under the secret-named key {key!r}"
    return None


def seconds_of(value):
    """systemd time span `value` in seconds ('30', '1min 30s', '500ms'), or None when it is not one; infinity is inf."""
    if value.strip() == "infinity":
        return float("inf")
    parts = re.fullmatch(r"(?:\s*\d+(?:\.\d+)?\s*[a-z]*)+", value.strip())
    if not parts:
        return None
    total = 0.0
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]*)", value):
        if unit not in TIME_UNITS:
            return None
        total += float(number) * TIME_UNITS[unit]
    return total


def line_of(text, needle):
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return 1


def stop_bound_of(document):
    """`(seconds, formula)`: the documented stop bound of a config document (D6): op_deadline_seconds + the store's 5 s
    connect + store_transaction_timeout_seconds + a 2 s margin; a missing or malformed value counts as its default."""
    defaults = {name: field.default for name, field in BridgeConfig.__dataclass_fields__.items()}

    def number(key):
        value = document.get(key, defaults[key]) if isinstance(document, dict) else defaults[key]
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else defaults[key]

    op, store = number("op_deadline_seconds"), number("store_transaction_timeout_seconds")
    formula = (f"op_deadline_seconds ({op:g}) + {STORE_CONNECT_SECONDS} + store_transaction_timeout_seconds ({store:g}) "
               f"+ {STOP_MARGIN_SECONDS}")
    return stop_bound_seconds(op, store), formula


def lint_unit(text, bound):
    """Violations `(line, rule, detail)` of the bridge unit; `bound` is `(seconds, formula)` of `stop_bound_of`."""
    config_seconds, formula = bound
    found, directives = [], {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in "#;" or line[0] == "[":
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        directives.setdefault(key, (number, value))
        pairs = []
        if key == "EnvironmentFile":
            found.append((number, "secret", "EnvironmentFile= may carry a secret: use a 0600 file named in the config"))
        elif key == "Environment":
            try:
                pairs = [item.partition("=")[::2] for item in shlex.split(value)]
            except ValueError:
                found.append((number, "secret", "an unparsable Environment= line"))
        for name, item in pairs:
            reason = template_secret_literal(name, item)
            if reason:
                found.append((number, "secret", reason))
        if key not in ("Environment", "EnvironmentFile"):
            reason = template_secret_literal("", value)
            if reason:
                found.append((number, "secret", reason))
    if "KillMode" not in directives:
        found.append((1, "kill-mode", "KillMode is missing"))
    if "TimeoutStopSec" not in directives:
        found.append((1, "stop-timeout", "TimeoutStopSec is missing"))
    else:
        number, value = directives["TimeoutStopSec"]
        seconds = seconds_of(value)
        if seconds is None:
            found.append((number, "stop-timeout", f"TimeoutStopSec={value} is not a time span"))
        elif seconds < config_seconds:
            found.append((number, "stop-timeout",
                          f"TimeoutStopSec={value} is below the stop bound {formula} = {config_seconds:g}s"))
    return found


def lint_config(text):
    """`(violations, stop bound)` of the bridge config template: unknown keys, secret literals, `BridgeConfig.parse`.

    The stop bound is `stop_bound_of` (D6): op_deadline_seconds, the store's connect, the enforced transaction allowance
    and a margin."""
    found = []
    try:
        document = json.loads(text)
    except ValueError as exc:
        return [(1, "config", f"not JSON: {exc}")], stop_bound_of({})
    if not isinstance(document, dict):
        return [(1, "config", "a JSON object is required")], stop_bound_of({})
    defaults = {name: field.default for name, field in BridgeConfig.__dataclass_fields__.items()}
    bound = stop_bound_of(document)

    def walk(key, value):
        if isinstance(value, dict):
            for inner_key, inner in value.items():
                walk(inner_key, inner)
        elif isinstance(value, list):
            for inner in value:
                walk(key, inner)
        elif isinstance(value, str):
            reason = template_secret_literal(str(key), value)
            if reason:
                found.append((line_of(text, f'"{key}"'), "secret", reason))
    walk("", document)
    for key in sorted(set(document) - set(defaults)):
        found.append((line_of(text, f'"{key}"'), "unknown-key", f"{key!r} is not a BridgeConfig key"))
    for key in sorted(set(defaults) - set(document)):
        found.append((1, "missing-key", f"{key!r} is missing (every BridgeConfig key is listed)"))
    if not found:
        def dummy(key, value):
            if isinstance(value, dict):
                return {dummy(key, k): dummy(key, v) for k, v in value.items()}
            if isinstance(value, list):
                return [dummy(key, item) for item in value]
            if isinstance(value, str) and PLACEHOLDER.search(value):
                if key == "owners":
                    return "ab" * 32
                if key == "org_d":
                    return "00000000-0000-4000-8000-000000000000"
                return PLACEHOLDER.sub(lambda m: "dummy-" + m.group(0)[1:-1].lower(), value)
            return value
        try:
            BridgeConfig.parse({key: dummy(key, value) for key, value in document.items()})
        except ContractError as exc:
            found.append((1, "config", f"BridgeConfig.parse refuses the template: {exc}"))
    return found, bound


def lint_compose(text):
    """Violations `(line, rule, detail)` of the relay compose template (parsed with line marks; comments never count)."""
    try:
        root = yaml_nodes(text)
    except yaml.YAMLError as exc:
        return [(getattr(getattr(exc, "problem_mark", None), "line", 0) + 1, "yaml", f"not YAML: {exc}")]
    found = []

    def scalar(node):
        return node.value if isinstance(node, yaml.ScalarNode) else None

    def at(node):
        return node.start_mark.line + 1

    def loopback_port(item):
        if isinstance(item, yaml.ScalarNode):
            if not item.value.startswith(LOOPBACK_PREFIXES):
                found.append((at(item), "port", f"published port {item.value!r} is not on loopback"))
        elif isinstance(item, yaml.MappingNode):
            fields = {scalar(k): v for k, v in item.value}
            host = scalar(fields.get("host_ip"))
            if host not in LOOPBACK_HOSTS:
                found.append((at(item), "port", f"published port has host_ip {host!r}: not loopback"))

    def walk(node, parent_key=None):
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = scalar(key_node)
                if key in ("privileged", "cap_add"):
                    found.append((at(key_node), "forbidden", f"{key} appears"))
                elif key == "network_mode" and scalar(value_node) == "host":
                    found.append((at(key_node), "forbidden", "network_mode: host"))
                elif key == "image":
                    image = scalar(value_node) or ""
                    if not DIGEST.search(image):
                        found.append((at(value_node), "image", f"image {image!r} is not pinned by sha256 digest"))
                elif key == "ports" and isinstance(value_node, yaml.SequenceNode):
                    for item in value_node.value:
                        loopback_port(item)
                if key is not None and scalar(value_node) is not None:
                    reason = template_secret_literal(key, scalar(value_node))
                    if reason:
                        found.append((at(value_node), "secret", reason))
                walk(value_node, key)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                text_value = scalar(item)
                if text_value is not None and parent_key in ("environment", "labels") and "=" in text_value:
                    name, _, rest = text_value.partition("=")
                    reason = template_secret_literal(name, rest)
                    if reason:
                        found.append((at(item), "secret", reason))
                walk(item, parent_key)
        elif isinstance(node, yaml.ScalarNode):
            if "docker.sock" in node.value:
                found.append((at(node), "forbidden", f"the docker socket ({node.value!r})"))
            for pattern, what in SECRET_VALUES:
                if pattern.search(INTERPOLATION.sub("", PLACEHOLDER.sub("PH", node.value))):
                    found.append((at(node), "secret", f"{what} in a literal value"))
    walk(root)
    return found


def lint_templates(directory):
    """The `file:line: rule: detail` lines of every violation in the three templates under `directory`."""
    texts, out = {}, []
    for relative in (BRIDGE_UNIT, BRIDGE_CONFIG, RELAY_COMPOSE):
        try:
            texts[relative] = (directory / relative).read_text(encoding="utf-8")
        except OSError as exc:
            out.append(f"{relative}:1: missing: {type(exc).__name__} reading the template")
    found = {}
    bound = stop_bound_of({})
    if BRIDGE_CONFIG in texts:
        found[BRIDGE_CONFIG], bound = lint_config(texts[BRIDGE_CONFIG])
    if BRIDGE_UNIT in texts:
        found[BRIDGE_UNIT] = lint_unit(texts[BRIDGE_UNIT], bound)
    if RELAY_COMPOSE in texts:
        found[RELAY_COMPOSE] = lint_compose(texts[RELAY_COMPOSE])
    for relative, violations in found.items():
        first = {(line, rule): detail for line, rule, detail in reversed(sorted(violations))}  # one per line and rule
        out.extend(f"{relative}:{line}: {rule}: {detail}" for (line, rule), detail in sorted(first.items()))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner-run Buzz D2 isolated end-to-end (needs Docker and Node; never run "
                                                 "by pytest)")
    parser.add_argument("--report", type=Path, help="report path (default: <run dir>/buzz_e2e_report.json)")
    parser.add_argument("--keep-on-failure", action="store_true",
                        help="on a failing step leave the stack running instead of `down -v`")
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP, help="the fork checkout holding desktop/ (D3 driver)")
    parser.add_argument("--lint-templates", action="store_true",
                        help="statically lint the D4 production templates (no Docker, no systemd); exit 1 names each line")
    parser.add_argument("--templates-dir", type=Path, default=TEMPLATES, help="the deploy directory --lint-templates reads")
    args = parser.parse_args(argv)
    if args.lint_templates:
        violations = lint_templates(args.templates_dir)
        for violation in violations:
            print(f"LINT {violation}", flush=True)
        print("templates lint-clean" if not violations else f"templates lint FAILED: {len(violations)} violation(s)")
        return 1 if violations else 0
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    tmp = SCRATCH / stamp
    tmp.mkdir(mode=0o700, parents=True)
    tmp.chmod(0o700)
    print(f"run directory: {tmp}", flush=True)
    return run_all(tmp.resolve(), args.report or tmp / "buzz_e2e_report.json", args.keep_on_failure, args.desktop)


if __name__ == "__main__":
    sys.exit(main())
