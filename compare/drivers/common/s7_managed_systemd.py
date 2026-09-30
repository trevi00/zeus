"""Shared S7 scenario steps (`delivery.managed_systemd`): the M7 managed Fleet target supervised by ONE owner-fixed
systemd unit, recorded BEFORE the move (DESIGN-s7 §2 row `delivery.managed_systemd`; INV-OWNER-ACTIONS-001,
aibox SPEC s14 G3).

Four case groups, each case labelled in the result and mirroring one M7 test of `tests/test_managed_systemd.py`
(207-428; the mapping is in `MIRRORS`):
- `registry`: only the owner-fixed unit can supervise a managed target; the registry grammar, the port map and
  `SystemdManagedFleetTarget.unit`.
- `coordinated`: five cases through the REAL `HostDelivery` coordinator, the side's own `SystemdManagedFleetTarget`,
  real sealed runtimes, the real trusted `supervise` process and the real sealed child (labelled `fixture`
  workload): the controller starts only the unit; a restarted controller recognizes the running unit; a failed
  unit restarts under the same checks and a requested stop is never restarted; a surviving old child refuses; a
  failed candidate rolls back through the same unit.
- `supervise`: `supervise` in process over a persisted request: nine refusals (one case per M7 parameter), each
  naming its reason before any launch, and the launch of the persisted request exactly once when the checks hold.
- `unit_state`: the unit state is read, never guessed.

**Fixtures (all LABELLED).** Reused from `s7_managed_runtime` by import, never copied: the pinned-identity fixture
source repository (revisions A and B), the `Managed` fixture (normalization, digest labels, state listings,
heartbeat waits, the labelled in-memory Fleet authority `fleet()`) and the child teardown. From `s7_delivery`: the
labelled `SerialStore`, `FakeGitHub`, `reviewed_release`, `plan_document` and `pin`.
- `SimulatedSystemd` (M7 `SimulatedSystemd`): the labelled control double of exactly `systemctl show|start` of ONE
  unit. `start` of an active unit is a no-op; `start` spawns the unit's ExecStart (`supervise`, with the labelled
  `SUPERVISE` gate that answers "paused and settled") in its own session, as a unit's control group would hold
  it; `show` reports that process. Every argv it receives is recorded, and any other verb raises. The invocation
  id is a labelled deterministic 32-hex string (M7 draws `uuid4().hex`); it is normalized to `<invocation>`.
- No real unit is installed, started or stopped: the golden pins the binding's contract (who launches, what is
  re-validated, what is never done), NOT systemd's cgroup behaviour on the host (`unreachable`, below).
- `TickClock` (M7 `Clock`): the coordinator's clock, advanced one second per tick. `Releases` reads the wall clock
  the driver keeps on real time (`api.sync_clock`), as in M7. The M7 `observer` is not wired (it emits events only).
- `determinism.install` freezes the wall clock; the live children write real heartbeats, so a labelled
  synchroniser keeps the fake clock on real time while a case runs. The in-process `supervise` cases set a labelled
  `INVOCATION_ID` so the journal line does not depend on the host's environment.

**What is recorded.** Per case: the tick trail (the stage, outcome, reason and error type of each tick, with the
transient `pending`/`unavailable`/`controller_busy` ticks dropped and consecutive repeats collapsed, because their
number depends on timing), results and refusal codes, the recorded `systemctl` argv (every `start` argv exactly,
the verbs, and the DISTINCT `show` argv; the number of `show` calls depends on timing and is not recorded), the
state-directory listing with normalized contents, the journal lines, the unit's starts count and alive/gone at
each named checkpoint. A sweep after each case fails the run on any live child and records `live_children: 0`.

`api` supplies `SystemdManagedFleetTarget`, `ManagedFleetTarget`, `supervise`, `owner_target`,
`validate_launch_request`, `launcher_environment`, `runtime_image`, `manifest_digest`, `fixture_config`,
`host_ports`, `owner_qualified_canary`, `startup_identity_canary`, `HostDelivery(store, org, **ports)`,
`organization()`, `releases(store)`, `BUCKET_INTENTS`, `LAUNCH_REQUEST_FILE`, `SUPERVISOR_JOURNAL`, `TARGET_FILE`,
`LAUNCH_REQUEST_SCHEMA`, `MODULE`, `EXIT_REFUSED`, `DESCRIPTOR_FILE`, `RECEIPT_FILE`, `STATE_FILE`, `PAUSE_FILE`, `STOP_FILE`,
`FIXTURE_JOBS_FILE`, `MANAGED_SYSTEMD_UNIT`, `KIND_MANAGED`, `KIND_MANAGED_SYSTEMD`, `ACTIVE`, `ROLLED_BACK`,
`CANARY_STARTUP`, `CANARY_FLEET`, `PLAN_SCHEMA`, `REGISTRY_SCHEMA`, `DESCRIPTOR_SCHEMA`, `DeliveryRefused`,
`MergeRefused`, `ContractError`, `descriptor_digest`, `managed_runtime_root`, `validate_targets`, `alive`,
`effective_profile_digest`, `Fleet`, `MemoryStore`, `SOURCE_PACKAGE`, `PACKAGE_DIR`, `sync_clock()` and
`reset_ids()`.

**Normalization is explicit, done here and identical on both sides**: exactly the rules of `s7_managed_runtime`
(imported), plus the simulated unit's invocation id (and the labelled in-process one) → `<invocation>`, applied
before the 32-hex rule. Revisions and digests stay literal; a descriptor digest the FIXTURE built is labelled
`<digest:NAME>` (a descriptor names `<root>/...`), NAME being the fixture's own label.

Unreachable without the real systemd (recorded, never attempted): `unreachable.host_cgroup`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import s7_delivery as D
import s7_managed_runtime as mr

until, proc_alive = mr.until, mr.proc_alive
TARGET_ID = mr.TARGET_ID
TRANSIENT = {"pending", "unavailable", "controller_busy"}
START = "2026-09-22T00:00:00+00:00"
LABELLED_INVOCATION = "1" * 32  # the in-process `supervise` cases' INVOCATION_ID (labelled)
SETTLED = {"paused": True, "settled": True}
# The unit's ExecStart: `supervise` of the product module named by argv[2] (`api.MODULE`), with a LABELLED gate that
# answers "paused and settled". It is imported by name because this module never imports the product.
SUPERVISE = ("import importlib, sys\n"
             "m = importlib.import_module(sys.argv[2])\n"
             "sys.exit(m.supervise(sys.argv[1], gate=lambda target_id, descriptor: {'paused': True, "
             "'settled': True}))\n")
# Which M7 test (tests/test_managed_systemd.py) each case mirrors.
MIRRORS = {
    "registry.owner_fixed_unit":
        "test_only_the_owner_fixed_unit_can_supervise_a_managed_target_and_a_plan_names_none",
    "coordinated.controller_starts_only_the_unit":
        "test_the_controller_starts_only_the_unit_and_the_sealed_runtime_reports_itself",
    "coordinated.restarted_controller":
        "test_a_restarted_controller_recognizes_the_running_unit_and_never_starts_a_second_fleet",
    "coordinated.failed_unit_and_requested_stop":
        "test_a_failed_unit_restarts_under_the_same_checks_and_a_requested_stop_is_never_restarted",
    "coordinated.surviving_old_child":
        "test_a_restart_whose_old_child_survived_refuses_instead_of_running_a_second_fleet",
    "coordinated.rollback_through_the_unit":
        "test_a_failed_candidate_rolls_back_to_the_predecessor_through_the_same_unit",
    "supervise.<fault>": "test_supervise_refuses_before_any_launch_and_names_why[<fault>-<code>] (nine cases)",
    "supervise.launches_once": "test_supervise_launches_exactly_the_persisted_request_once_the_checks_hold",
    "unit_state.read_never_guessed": "test_the_unit_state_is_read_never_guessed",
}
FAULTS = [("no_request", "launch_request_invalid"), ("foreign_request", "launch_request_foreign"),
          ("changed_descriptor", "descriptor_changed"), ("changed_manifest", "runtime_manifest_changed"),
          ("stop_requested", "stop_requested"), ("debt_held", "fleet_debt_held"),
          ("debt_unknown", "fleet_debt_unknown"), ("gate_down", "fleet_pause_unknown"),
          ("wrong_kind", "launch_request_foreign")]
UNREACHABLE = {"host_cgroup": "KillMode=control-group, Restart=on-failure and the unit's real control group are "
                              "systemd's own behaviour on the host: M7's docstring names them a live "
                              "qualification item, and no real unit is installed, started or stopped here"}


class TickClock:
    """LABELLED (M7 `tests/test_host_delivery.py::Clock`): the coordinator's stage deadlines and fence read it."""

    def __init__(self, start=START):
        self.at = datetime.fromisoformat(start)

    def __call__(self):
        return self.at.isoformat()

    def advance(self, seconds):
        self.at += timedelta(seconds=seconds)
        return self()


class SimulatedSystemd:
    """LABELLED simulation of exactly the `systemctl show|start` of one unit (M7 `SimulatedSystemd`). `start` of an
    active unit is a no-op (systemd semantics); every argv is recorded so the golden proves nothing else was
    asked."""

    def __init__(self, fx, target):
        self.api, self.fx, self.state_dir = fx.api, fx, Path(target["state_dir"])
        self.unit = fx.api.MANAGED_SYSTEMD_UNIT + ".service"
        self.calls, self.process, self.invocation, self.starts = [], None, None, 0

    def __call__(self, argv, timeout=None, **_):
        self.calls.append(list(argv))
        assert argv[0] == "systemctl" and argv[2] == self.unit, argv
        if argv[1] == "start":
            if not self.active():
                self.spawn()
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1] == "show":
            state = "active" if self.active() else ("inactive" if self.process is None
                                                    or self.process.returncode == 0 else "failed")
            pid = self.process.pid if self.active() else 0
            out = f"ActiveState={state}\nMainPID={pid}\nInvocationID={self.invocation or ''}\n"
            return subprocess.CompletedProcess(argv, 0, out, "")
        raise AssertionError("the binding may only show or start its unit: " + repr(argv))

    def active(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def spawn(self):
        """The unit's ExecStart in its own session, with the unit's invocation id (a labelled deterministic one)."""
        self.starts += 1
        self.invocation = hashlib.sha256(b"labelled-invocation-%d" % self.fx.next_invocation()).hexdigest()[:32]
        self.fx.invocations.add(self.invocation)
        env = {**self.api.launcher_environment(), "INVOCATION_ID": self.invocation}
        self.process = subprocess.Popen([sys.executable, "-c", SUPERVISE, str(self.state_dir), self.api.MODULE], env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True)

    def restart_after_failure(self):
        """`Restart=on-failure` after the unit's main process failed: one more ExecStart."""
        assert not self.active() and self.process.returncode not in (0, None)
        self.spawn()

    def crash(self, *, cgroup_cleanup=True):
        """LABELLED injected failure of the unit's main process. With `cgroup_cleanup` the rest of the unit's
        processes end too, as KillMode=control-group does when the main process dies; without it the sealed child
        (its own session) survives, the case `supervise` must refuse to double."""
        os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=30)
        receipt = self.fx.read_state({"state_dir": str(self.state_dir)}, self.api.RECEIPT_FILE) or {}
        child = receipt.get("pid")
        if cgroup_cleanup and self.api.alive(child):
            os.killpg(child, signal.SIGKILL)
            until(lambda: not self.api.alive(child), 20)
        return child

    def stop_process(self):
        """Test cleanup only: end the simulated unit's process tree (`run_owned` reclaims on SIGTERM)."""
        if self.active():
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=30)

    def view(self) -> dict:
        """What was asked of systemd: every `start` argv exactly, the verbs, and the distinct `show` argv."""
        shows = []
        for argv in self.calls:
            if argv[1] == "show" and argv not in shows:
                shows.append(argv)
        return {"start_argv": [argv for argv in self.calls if argv[1] == "start"],
                "verbs": sorted({argv[1] for argv in self.calls}), "distinct_show_argv": shows,
                "starts": self.starts}


class Systemd(mr.Managed):
    """`s7_managed_runtime.Managed` plus the simulated units of the current case and the invocation ids."""

    def __init__(self, api, base):
        super().__init__(api, base)
        self.units, self.invocations, self.invocation_serial = {}, set(), 0

    def next_invocation(self) -> int:
        self.invocation_serial += 1
        return self.invocation_serial

    def n(self, value):
        if isinstance(value, str) and value in self.invocations:
            return "<invocation>"
        return super().n(value)

    def systemd_document(self, **overrides) -> tuple:
        """LABELLED: the owner-fixed unit's registry document and its validated target (M7 `systemd_target`)."""
        api = self.api
        entry = {"target_id": TARGET_ID, "kind": api.KIND_MANAGED_SYSTEMD, "root": str(self.case_dir / "managed"),
                 "state_dir": str(self.case_dir / ("state-" + TARGET_ID)), "service": api.MANAGED_SYSTEMD_UNIT,
                 "source": str(self.shared_source()["root"]), "python": mr.PY, "environment_lock": mr.LOCK_SHA,
                 **overrides}
        document = {"schema": api.REGISTRY_SCHEMA, "targets": [entry]}
        target = api.validate_targets(document)["targets"][0]
        self.live.append(target)
        return document, target

    def unit_for(self, target) -> SimulatedSystemd:
        unit = SimulatedSystemd(self, target)
        self.units.setdefault(target["state_dir"], []).append(unit)
        return unit

    def teardown(self, target):
        """Test cleanup only: end each simulated unit's tree, then any sealed child that outlived it."""
        for unit in self.units.pop(target["state_dir"], []):
            unit.stop_process()
        receipt = self.read_state(target, self.api.RECEIPT_FILE)
        child = receipt.get("pid") if isinstance(receipt, dict) else None
        if child is not None and self.api.alive(child):
            until(lambda: not self.api.alive(child), 10)
            if self.api.alive(child):
                with contextlib.suppress(OSError):
                    os.killpg(child, signal.SIGKILL)
                until(lambda: not self.api.alive(child), 20)
        super().teardown(target)

    def journal(self, target) -> list:
        """The supervisor journal's lines, normalized; absent → None."""
        path = self.state(target, self.api.SUPERVISOR_JOURNAL)
        if not path.exists():
            return None
        return [self.n(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]

    def listing(self, target) -> dict:
        """The state directory with normalized contents; the journal as its lines."""
        out = self.state_listing(target)
        if self.api.SUPERVISOR_JOURNAL in out:
            out[self.api.SUPERVISOR_JOURNAL] = self.journal(target)
        return out


# ---- the coordinated system -----------------------------------------------------------------------------------
def coordinated(fx, *, canary=None):
    """M7 `system_for`: the real coordinator over the systemd-supervised managed target and the labelled unit."""
    api = fx.api
    document, target = fx.systemd_document()
    unit = fx.unit_for(target)
    host = api.SystemdManagedFleetTarget(workload="fixture", fleet=fx.fleet(), runner=unit)
    store, org, clock = D.SerialStore(api), api.organization(), TickClock()
    release = D.reviewed_release(api, store, org)
    delivery = api.HostDelivery(store, org, github=D.FakeGitHub(api), hosts={api.KIND_MANAGED_SYSTEMD: host},
                                canaries={api.CANARY_STARTUP: api.startup_identity_canary,
                                          api.CANARY_FLEET: api.owner_qualified_canary},
                                clock=clock, enabled=True, resume_seconds=0)
    delivery.register_targets(document)
    source = fx.shared_source()
    plan = D.plan_document(api, release, target_id=TARGET_ID, image=api.runtime_image(target, dict(os.environ)),
                           profile=fx.profile, descriptor_revision=source["a"], consumption_timeout=900,
                           canary=canary)
    delivery.register(plan, D.pin())
    return {"store": store, "org": org, "clock": clock, "delivery": delivery, "host": host, "unit": unit,
            "plan": plan, "target": target, "document": document}


def advance(system, until_stage, *, limit=200):
    """M7 `advance`: tick until the stage or a stop; a transient outcome waits for the real child."""
    results = []
    for _ in range(limit):
        result = system["delivery"].tick()
        system["clock"].advance(1)
        results.append(result)
        if result["stage"] == until_stage or result["outcome"] in {"blocked", "refused"}:
            return results
        if result["outcome"] in TRANSIENT:
            time.sleep(0.1)
    return results


def trail_of(results) -> list:
    """The stage trail: stage, outcome, reason and error type per tick; transient ticks dropped and repeats collapsed
    (their number depends on timing)."""
    rows = []
    for result in results:
        if result["outcome"] in TRANSIENT:
            continue
        row = [result["stage"], result["outcome"], result["reason_code"], result["error_type"]]
        if not rows or rows[-1] != row:
            rows.append(row)
    return rows


def alive_view(fx, system, **pids) -> dict:
    """Alive/gone at a checkpoint: the unit's process, the launcher and child of the state directory, and any
    named extra pid."""
    now = fx.alive(system["target"])
    return {"unit_active": system["unit"].active(), "launcher": now["launcher"], "child": now["child"],
            **{name: (None if pid is None else bool(fx.api.alive(pid))) for name, pid in pids.items()}}


def activate(fx, system, out):
    """Tick to `active` and record the trail; returns the first receipt."""
    results = advance(system, fx.api.ACTIVE)
    out["trail"] = trail_of(results)
    out["reached_active"] = results[-1]["stage"] == fx.api.ACTIVE
    assert out["reached_active"], out["trail"]
    label_descriptor(fx, system, out)  # the coordinator's descriptor names <root>/..., so its digest is labelled
    return fx.read_state(system["target"], fx.api.RECEIPT_FILE)


def label_descriptor(fx, system, out, label="coordinated.A"):
    """The descriptor the coordinator wrote, equal to the fixture's own and therefore labelled like it."""
    target, api = system["target"], fx.api
    written = fx.read_state(target, api.DESCRIPTOR_FILE)
    built = fx.desc(target, label, "a")
    out["descriptor_is_the_fixtures"] = written == built
    return written


# ======================================================================================================
# 1. registry
# ======================================================================================================
def case_owner_fixed_unit(fx):
    api, source = fx.api, fx.shared_source()
    out = {}
    _, target = fx.systemd_document()
    out["target"] = {"kind": target["kind"], "service": target["service"],
                     "kind_is_systemd": target["kind"] == api.KIND_MANAGED_SYSTEMD,
                     "service_is_the_fixed_unit": target["service"] == api.MANAGED_SYSTEMD_UNIT,
                     "unit": api.MANAGED_SYSTEMD_UNIT}
    out["other_units"] = {name: fx.attempt(lambda name=name: fx.systemd_document(service=name))
                          for name in ("zeus-aibox-fleet", "zeus-aibox-monitor-collect", "sshd",
                                       "zeus-aibox-managed-fleet2")}
    out["port"] = type(api.host_ports()[api.KIND_MANAGED_SYSTEMD]).__name__
    out["unit_of_other_service"] = fx.attempt(
        lambda: api.SystemdManagedFleetTarget.unit({**target, "service": "zeus-aibox-fleet"}))
    out["unit_of_target"] = api.SystemdManagedFleetTarget.unit(target)
    # The sealed-runtime rules are the managed target's own: the descriptor root is derived, never supplied.
    desc = fx.desc(target, "registry.A", "a")
    out["descriptor_root_is_derived"] = desc["root"] == api.managed_runtime_root(target, source["a"])
    return fx.n(out)


# ======================================================================================================
# 2. coordinated
# ======================================================================================================
def case_controller_starts_only_the_unit(fx):
    api = fx.api
    system = coordinated(fx)
    target, unit, out = system["target"], system["unit"], {}
    first = activate(fx, system, out)
    written = fx.read_state(target, api.DESCRIPTOR_FILE)
    a = fx.shared_source()["a"]
    out["receipt"] = {"revision_is_a": first["revision"] == a, "runtime_root_ends_with_a": first["runtime_root"].endswith(a),
                      "descriptor_is_the_written_one": first["descriptor_sha256"] == fx.digest(written)}
    out["systemctl"] = unit.view()
    request = api.validate_launch_request(fx.read_state(target, api.LAUNCH_REQUEST_FILE))
    out["request"] = request
    out["request_names_the_descriptor"] = request["descriptor_sha256"] == fx.digest(written)
    launch = fx.read_state(target, api.STATE_FILE)
    out["launch_record"] = {"pid_is_the_units_main_pid": launch["pid"] == unit.process.pid,
                            "invocation_is_the_units": launch["invocation_id"] == unit.invocation,
                            "service": launch["service"]}
    out["target_snapshot_is_owner_target"] = fx.read_state(target, api.TARGET_FILE) == api.owner_target(target)
    out["journal_events"] = [event["event"] for event in fx.journal(target)]
    out["journal_invocation_is_the_units"] = fx.journal(target)[0]["invocation_id"] == "<invocation>"
    out["work"] = fx.await_work(system["host"], target, "idle")["state"]
    out["alive"] = alive_view(fx, system)
    out["state_dir"] = fx.listing(target)
    return fx.n(out)


def case_restarted_controller(fx):
    api = fx.api
    system = coordinated(fx)
    target, unit, out = system["target"], system["unit"], {}
    first = activate(fx, system, out)
    out["work"] = fx.await_work(system["host"], target, "idle")["state"]  # the instance's OWN first heartbeat
    out["systemctl_before_restart"] = unit.view()
    # LABELLED: the delivery controller restarts (new process objects, same durable state and unit).
    restarted = api.SystemdManagedFleetTarget(workload="fixture", fleet=fx.fleet(), runner=unit)
    desc = fx.read_state(target, api.DESCRIPTOR_FILE)
    again = restarted.start(target, desc)
    out["restart"] = {"started": again["started"], "recovered": again.get("recovered"),
                      "same_instance": again["instance_id"] == first["instance_id"],
                      "keys": sorted(again)}
    out["running"] = restarted.running(target)
    out["starts_after_restart"] = unit.starts
    # A replayed start request to systemd for an active unit is a no-op, never a second runner.
    unit(["systemctl", "start", unit.unit])
    out["starts_after_replay"] = unit.starts
    out["same_instance_after_replay"] = fx.read_state(target, api.RECEIPT_FILE)["instance_id"] == first["instance_id"]
    out["systemctl"] = unit.view()
    out["alive"] = alive_view(fx, system)
    out["state_dir"] = fx.listing(target)
    return fx.n(out)


def case_failed_unit_and_requested_stop(fx):
    api = fx.api
    system = coordinated(fx)
    target, unit, host, out = system["target"], system["unit"], system["host"], {}
    first = activate(fx, system, out)
    fx.await_work(host, target, "idle")
    out["before_crash"] = alive_view(fx, system)
    # LABELLED injected crash of the unit's main process: the unit fails and its cgroup is emptied.
    unit.crash()
    out["after_crash"] = {**alive_view(fx, system, first_child=first["pid"]),
                          "unit_returncode_nonzero": unit.process.returncode != 0}
    unit.restart_after_failure()
    until(lambda: fx.read_state(target, api.RECEIPT_FILE)["instance_id"] != first["instance_id"], 30)
    second = fx.read_state(target, api.RECEIPT_FILE)
    out["restarted"] = {"new_instance": second["instance_id"] != first["instance_id"],
                        "same_revision": second["revision"] == first["revision"], "starts": unit.starts,
                        "first_child_gone": not api.alive(first["pid"])}
    out["journal_after_restart"] = [event["event"] for event in fx.journal(target)]
    fx.await_work(host, target, "idle")
    out["alive_second"] = alive_view(fx, system)
    # A stop that the managed target requested is final: a restart of the unit starts nothing.
    stopped = host.stop(target)
    until(lambda: not unit.active(), 30)
    out["stop"] = {"result": stopped, "unit_active_after": unit.active()}
    unit.process.returncode = 1  # LABELLED: pretend systemd saw a failure and restarts anyway
    unit.restart_after_failure()
    out["restart_after_stop"] = {"exit": unit.process.wait(timeout=30), "starts": unit.starts}
    out["journal"] = fx.journal(target)
    out["alive_end"] = alive_view(fx, system)
    out["systemctl"] = unit.view()
    out["state_dir"] = fx.listing(target)
    return fx.n(out)


def case_surviving_old_child(fx):
    api = fx.api
    system = coordinated(fx)
    target, unit, out = system["target"], system["unit"], {}
    first = activate(fx, system, out)
    fx.await_work(system["host"], target, "idle")
    survivor = unit.crash(cgroup_cleanup=False)  # LABELLED: the old sealed child outlives its unit
    out["survivor"] = {"is_the_first_child": survivor == first["pid"], "alive": bool(api.alive(survivor))}
    unit.restart_after_failure()
    out["restart"] = {"exit": unit.process.wait(timeout=30), "starts": unit.starts}
    out["journal"] = fx.journal(target)
    out["no_second_instance"] = fx.read_state(target, api.RECEIPT_FILE)["instance_id"] == first["instance_id"]
    out["alive"] = alive_view(fx, system, survivor=survivor)
    out["systemctl"] = unit.view()
    out["state_dir"] = fx.listing(target)
    return fx.n(out)


def case_rollback_through_the_unit(fx):
    api = fx.api
    system = coordinated(fx)
    target, unit, host, out = system["target"], system["unit"], system["host"], {}
    source = fx.shared_source()
    activate(fx, system, out)
    good = fx.read_state(target, api.DESCRIPTOR_FILE)
    fx.await_work(host, target, "idle")
    release = D.reviewed_release(api, system["store"], system["org"], record_candidate={
        **D.candidate(), "base": system["delivery"].github.main, "revision": "5" * 40, "branch": "harness/two",
        "task_id": "two"})
    plan = D.plan_document(api, release, plan_id="managed-plan-2", target_id=TARGET_ID,
                           expected=fx.digest(good), image=api.runtime_image(target, dict(os.environ)),
                           profile=fx.profile, canary=api.CANARY_FLEET, descriptor_revision=source["b"],
                           consumption_timeout=900)
    system["delivery"].register(plan, D.pin(path="docs/zeus/operations/delivery-2.json"))
    candidate = fx.desc(target, "coordinated.B", "b", predecessor=fx.digest(good))
    results = advance(system, api.ROLLED_BACK)
    out["rollback_trail"] = trail_of(results)
    out["rolled_back"] = results[-1]["stage"] == api.ROLLED_BACK
    assert out["rolled_back"], out["rollback_trail"]
    restored = fx.read_state(target, api.RECEIPT_FILE)
    out["restored"] = {"revision_is_a": restored["revision"] == source["a"],
                       "descriptor_is_the_predecessors": fx.read_state(target, api.DESCRIPTOR_FILE) == good,
                       "candidate_descriptor_labelled": fx.digest(candidate) != fx.digest(good)}
    # Forward start, candidate start, predecessor restart: each only `systemctl start`, never stop/kill.
    out["systemctl"] = unit.view()
    with system["store"].transaction() as tx:
        intent = tx.get(api.BUCKET_INTENTS, "managed-plan-2")
    out["rollback_verified"] = intent["rollback"]["verified"]
    out["restored_work"] = fx.await_work(host, target, "idle")["state"]  # the restored instance's OWN heartbeat
    out["journal_events"] = [event["event"] for event in fx.journal(target)]
    out["alive"] = alive_view(fx, system)
    out["state_dir"] = fx.listing(target)
    return fx.n(out)


# ======================================================================================================
# 3. supervise
# ======================================================================================================
def persisted(fx, tag):
    """M7 `persisted`: a sealed runtime, the descriptor, the target snapshot and the launch request as `_launch`
    writes them, without starting anything."""
    api = fx.api
    _, target = fx.systemd_document()
    host = api.SystemdManagedFleetTarget(workload="fixture", fleet=fx.fleet(), runner=None)
    desc = fx.desc(target, tag + ".A", "a")
    host.materialize(target, desc)
    host.switch(target, desc, expected=None)
    manifest = host.verify(target, desc)
    Path(target["state_dir"]).mkdir(parents=True, exist_ok=True)
    fx.state(target, api.TARGET_FILE).write_text(json.dumps(api.owner_target(target)), encoding="utf-8")
    request = {"schema": api.LAUNCH_REQUEST_SCHEMA, "target_id": target["target_id"],
               "descriptor_sha256": fx.digest(desc), "manifest_sha256": api.manifest_digest(manifest),
               "workload": "fixture", "requested_at": "2026-09-25T00:00:00+00:00"}
    fx.state(target, api.LAUNCH_REQUEST_FILE).write_text(json.dumps(request), encoding="utf-8")
    return target, desc, request


def run_supervise(fx, target, **kwargs):
    """`supervise` in process, under the labelled INVOCATION_ID so the journal line is host-independent."""
    fx.invocations.add(LABELLED_INVOCATION)
    with mock.patch.dict(os.environ, {"INVOCATION_ID": LABELLED_INVOCATION}):
        return fx.api.supervise(target["state_dir"], **kwargs)


def supervise_case(fault, code):
    def case(fx):
        api = fx.api
        target, desc, request = persisted(fx, "supervise-" + fault)
        root = Path(target["state_dir"])
        gates = []

        def settled(target_id, digest):
            gates.append((target_id, digest))
            return SETTLED

        gate = settled
        if fault == "no_request":
            (root / api.LAUNCH_REQUEST_FILE).unlink()
        elif fault == "foreign_request":
            (root / api.LAUNCH_REQUEST_FILE).write_text(json.dumps({**request, "target_id": "other"}), encoding="utf-8")
        elif fault == "changed_descriptor":
            (root / api.LAUNCH_REQUEST_FILE).write_text(json.dumps({**request, "descriptor_sha256": "0" * 64}),
                                                        encoding="utf-8")
        elif fault == "changed_manifest":
            (root / api.LAUNCH_REQUEST_FILE).write_text(json.dumps({**request, "manifest_sha256": "0" * 64}),
                                                        encoding="utf-8")
        elif fault == "stop_requested":
            (root / (api.STOP_FILE + ".json")).write_text("{}", encoding="utf-8")
        elif fault == "debt_held":
            def gate(target_id, digest):
                gates.append((target_id, digest))
                return {"paused": True, "settled": False}
        elif fault == "debt_unknown":
            def gate(target_id, digest):
                gates.append((target_id, digest))
                return {"paused": True, "settled": False, "reason_code": "debt_unknown"}
        elif fault == "gate_down":
            def gate(target_id, digest):
                gates.append((target_id, digest))
                raise ConnectionError("labelled injected unreachable Fleet store")
        elif fault == "wrong_kind":
            (root / api.TARGET_FILE).write_text(json.dumps({**api.owner_target(target), "kind": "managed_fleet"}),
                                                encoding="utf-8")
        launched = []
        exit_code = run_supervise(fx, target, gate=gate, launcher=lambda *args: launched.append(args) or 0)
        events = fx.journal(target)
        return fx.n({"fault": fault, "exit": exit_code, "exit_is_refused": exit_code == api.EXIT_REFUSED,
                     "launched": launched, "gate_calls": gates, "journal": events,
                     "last_event_is_the_refusal": events[-1]["event"] == "refused"
                     and events[-1]["reason_code"] == code, "expected_reason": code,
                     "state_dir": fx.listing(target)})
    return case


def case_launches_once(fx):
    target, desc, request = persisted(fx, "supervise-once")
    launched, gates = [], []
    code = run_supervise(fx, target, gate=lambda t, d: gates.append((t, d)) or SETTLED,
                         launcher=lambda *args: launched.append(args) or 0)
    return fx.n({"exit": code, "gate_calls": gates,
                 "gate_named_the_request": gates == [(target["target_id"], request["descriptor_sha256"])],
                 "launched": launched,
                 "launched_exactly_the_request": launched == [(str(Path(target["state_dir"])),
                                                               request["descriptor_sha256"], "fixture")],
                 "journal": fx.journal(target), "state_dir": fx.listing(target)})


# ======================================================================================================
# 4. unit state
# ======================================================================================================
def case_unit_state_read(fx):
    api = fx.api
    _, target = fx.systemd_document()
    calls = []

    def answering(state):
        def runner(argv, timeout=None):
            calls.append([list(argv), timeout])
            return subprocess.CompletedProcess(argv, 0, f"ActiveState={state}\n", "")
        return runner

    def broken(argv, timeout=None):
        calls.append([list(argv), timeout])
        return subprocess.CompletedProcess(argv, 1, "", "Failed to connect to bus")

    out = {"states": {}}
    for state in ("active", "activating", "deactivating", "reloading", "inactive", "failed", "maintenance", ""):
        host = api.SystemdManagedFleetTarget(fleet=fx.fleet(), runner=answering(state))
        out["states"][state or "<empty>"] = fx.attempt(lambda host=host: host.unit_active(target))
    # M7's two cases: an unknown ActiveState, and a failing `systemctl show`.
    for name, runner in (("unknown", answering("maintenance")), ("broken", broken)):
        try:
            api.SystemdManagedFleetTarget(fleet=fx.fleet(), runner=runner).unit_active(target)
            out[name] = "returned"
        except RuntimeError as exc:
            out[name] = {"raised": "RuntimeError", "message": str(exc)}
    out["show_argv"] = calls[0][0]
    out["timeout"] = calls[0][1]
    return fx.n(out)


GROUPS = [
    ("registry", [("owner_fixed_unit", case_owner_fixed_unit)]),
    ("coordinated", [("controller_starts_only_the_unit", case_controller_starts_only_the_unit),
                     ("restarted_controller", case_restarted_controller),
                     ("failed_unit_and_requested_stop", case_failed_unit_and_requested_stop),
                     ("surviving_old_child", case_surviving_old_child),
                     ("rollback_through_the_unit", case_rollback_through_the_unit)]),
    ("supervise", [(fault, supervise_case(fault, code)) for fault, code in FAULTS]
     + [("launches_once", case_launches_once)]),
    ("unit_state", [("read_never_guessed", case_unit_state_read)]),
]


def run(api) -> dict:
    result, counts, live = {}, {}, 0
    stop, thread = mr.synchronised(api)
    try:
        with tempfile.TemporaryDirectory(prefix="s7-managed-systemd-") as raw:
            fx = Systemd(api, Path(raw).resolve())
            source = fx.shared_source()
            result["revisions"] = {"a": source["a"], "b": source["b"], "identical_on_rebuild": True}
            for name, cases in GROUPS:
                result[name] = {}
                for case, function in cases:
                    api.reset_ids()
                    fx.case_dir = fx.base / f"{name}-{case}"
                    fx.case_dir.mkdir()
                    try:
                        result[name][case] = function(fx)
                    finally:
                        targets, fx.live = fx.live, []
                        failure = None
                        for target in targets:
                            try:
                                fx.teardown(target)
                            except Exception as exc:  # the sweep below still runs
                                failure = failure or exc
                        live += fx.sweep(f"{name}.{case}")
                        if failure is not None:
                            raise failure
                counts[name] = len(result[name])
            result["unreachable"] = dict(UNREACHABLE)
            result["live_children"] = live
            result["cases_per_group"] = counts
    finally:
        stop.set()
        thread.join(10)
    return result
