"""INV-OWNER-ACTIONS-001, aibox-migration-001 SPEC s14 G3: the managed Fleet target supervised by ONE
owner-fixed systemd unit.

The host side is real, reusing `test_managed_runtime`'s labelled fixtures: a disposable source repository
with two revisions, real sealed runtimes, the real trusted launcher (`launch`) and the real sealed child
(`entry`, labelled `fixture` workload), the real `HostDelivery` with `FakeGitHub`. What is SIMULATED and
labelled is systemd itself (`SimulatedSystemd`): `systemctl start` spawns the unit's ExecStart
(`managed_runtime.supervise`) in its own session, as a unit's own control group would hold it, and
`systemctl show` reports that process. No real unit is installed, started or stopped, so this proves the
binding's contract (who launches, what is re-validated, what is never done), NOT systemd's cgroup
behaviour on the host - that remains a live qualification item.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from test_host_delivery import (
    PROFILE,
    Clock,
    FakeGitHub,
    SerialStore,
    candidate,
    observer_for,
    pin,
    plan_document,
    reviewed_release,
    runtime_image,
)
from test_managed_runtime import (
    await_work,
    descriptor,
    fixture_fleet,
    make_source,
    read,
    registry,
    state,
    teardown,
)

from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    _alive,
    host_ports,
    owner_qualified_canary,
    startup_identity_canary,
)
from codex_harness.adapters.managed_runtime import (
    LAUNCH_REQUEST_FILE,
    SUPERVISOR_JOURNAL,
    TARGET_FILE,
    SystemdManagedFleetTarget,
    launcher_environment,
    owner_target,
    supervise,
    validate_launch_request,
)
from codex_harness.application.host_delivery import BUCKET_INTENTS, HostDelivery
from codex_harness.bootstrap import organization
from codex_harness.domain.host_delivery import (
    ACTIVE,
    CANARY_FLEET,
    CANARY_STARTUP,
    KIND_MANAGED_SYSTEMD,
    MANAGED_SYSTEMD_UNIT,
    ROLLED_BACK,
    DeliveryRefused,
    descriptor_digest,
    managed_runtime_root,
    validate_targets,
)

needs_profile = pytest.mark.skipif(PROFILE is None, reason="this checkout packages no worker profile")
posix_only = pytest.mark.skipif(os.name == "nt", reason="the systemd binding is Linux-only (aibox)")
TARGET_ID = "managed-fleet"
UNIT = MANAGED_SYSTEMD_UNIT + ".service"
# LABELLED fixture gate of the simulated unit: the debt authority inside the unit process is the host
# store's Fleet in production (`managed_runtime.fleet_gate`); here it answers "paused and settled".
SUPERVISE = ("import sys\n"
             "from codex_harness.adapters import managed_runtime as m\n"
             "sys.exit(m.supervise(sys.argv[1], gate=lambda target_id, descriptor: {'paused': True, "
             "'settled': True}))\n")


class SimulatedSystemd:
    """LABELLED simulation of exactly the `systemctl show|start` of one unit. `start` of an active unit is
    a no-op (systemd semantics); every argv is recorded so a test can prove nothing else was asked."""

    def __init__(self, state_dir: Path):
        self.state_dir, self.calls, self.process, self.invocation, self.starts = state_dir, [], None, None, 0

    def __call__(self, argv, timeout=None, **_):
        self.calls.append(list(argv))
        assert argv[0] == "systemctl" and argv[2] == UNIT, argv
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
        """The unit's ExecStart in its own session, with the unit's invocation id."""
        self.invocation, self.starts = uuid.uuid4().hex, self.starts + 1
        env = {**launcher_environment(), "INVOCATION_ID": self.invocation}
        self.process = subprocess.Popen([sys.executable, "-c", SUPERVISE, str(self.state_dir)], env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True)

    def restart_after_failure(self):
        """`Restart=on-failure` after the unit's main process failed: one more ExecStart."""
        assert not self.active() and self.process.returncode not in (0, None)
        self.spawn()

    def crash(self, *, cgroup_cleanup=True):
        """LABELLED injected failure of the unit's main process. With `cgroup_cleanup` the rest of the
        unit's processes end too, as KillMode=control-group does when the main process dies; without it
        the sealed child (its own session) survives, the case `supervise` must refuse to double."""
        os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=30)
        receipt = read(self.state_dir / RECEIPT_FILE) if (self.state_dir / RECEIPT_FILE).exists() else {}
        child = receipt.get("pid")
        if cgroup_cleanup and _alive(child):
            os.killpg(child, signal.SIGKILL)
        deadline = time.monotonic() + 20
        while cgroup_cleanup and _alive(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        return child


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """The managed suite's labelled disposable source repository (revisions A and B)."""
    return make_source(tmp_path_factory.mktemp("systemd-source") / "source")


def systemd_target(tmp_path, source_root, **overrides):
    document = registry(tmp_path, source_root, **{"kind": KIND_MANAGED_SYSTEMD, "service": MANAGED_SYSTEMD_UNIT,
                                                  **overrides})
    return document, validate_targets(document)["targets"][0]


def system_for(tmp_path, source, *, canary=CANARY_STARTUP):
    document, target = systemd_target(tmp_path, source["root"])
    unit = SimulatedSystemd(Path(target["state_dir"]))
    host = SystemdManagedFleetTarget(workload="fixture", fleet=fixture_fleet(), runner=unit)
    store, org, clock = SerialStore(), organization(), Clock()
    release = reviewed_release(store, org)
    delivery = HostDelivery(store, org, github=FakeGitHub(), hosts={KIND_MANAGED_SYSTEMD: host},
                            canaries={CANARY_STARTUP: startup_identity_canary, CANARY_FLEET: owner_qualified_canary},
                            clock=clock, observer=observer_for(store), enabled=True, resume_seconds=0)
    delivery.register_targets(document)
    plan = plan_document(release, target_id=TARGET_ID, image=runtime_image(source["root"]), profile=PROFILE,
                         descriptor_revision=source["a"], consumption_timeout=900, canary=canary)
    delivery.register(plan, pin())
    return {"store": store, "org": org, "clock": clock, "delivery": delivery, "host": host, "unit": unit,
            "plan": plan, "target": target, "document": document}


def advance(system, until, *, limit=200):
    results = []
    for _ in range(limit):
        result = system["delivery"].tick()
        system["clock"].advance(1)
        results.append(result)
        if result["stage"] == until or result["outcome"] in {"blocked", "refused"}:
            return results
        if result["outcome"] in {"pending", "unavailable", "controller_busy"}:
            time.sleep(0.1)
    return results


def trail(results):
    return "\n".join(str((r["stage"], r["outcome"], r["reason_code"], r["error_type"])) for r in results)


def finish(system):
    """Test cleanup only: end the simulated unit's process tree (run_owned reclaims on SIGTERM)."""
    unit = system["unit"]
    try:
        teardown(system["target"])
    finally:
        if unit.active():
            os.killpg(unit.process.pid, signal.SIGTERM)
            unit.process.wait(timeout=30)


# ----- registry grammar: the unit is owner-fixed code configuration --------------------------------------
@posix_only
def test_only_the_owner_fixed_unit_can_supervise_a_managed_target_and_a_plan_names_none(tmp_path, source):
    document, target = systemd_target(tmp_path, source["root"])
    assert target["kind"] == KIND_MANAGED_SYSTEMD and target["service"] == MANAGED_SYSTEMD_UNIT
    for name in ("zeus-aibox-fleet", "zeus-aibox-monitor-collect", "sshd", "zeus-aibox-managed-fleet2"):
        with pytest.raises(DeliveryRefused) as refused:
            systemd_target(tmp_path, source["root"], service=name)
        assert refused.value.reason_code == "target_unit_not_allowed"
    assert isinstance(host_ports()[KIND_MANAGED_SYSTEMD], SystemdManagedFleetTarget)
    with pytest.raises(DeliveryRefused) as refused:
        SystemdManagedFleetTarget.unit({**target, "service": "zeus-aibox-fleet"})
    assert refused.value.reason_code == "target_unit_not_allowed"
    # The sealed-runtime rules are the managed target's own: the descriptor root is derived, never supplied.
    desc = descriptor(target, source["root"], source["a"])
    assert desc["root"] == managed_runtime_root(target, source["a"])


# ----- activation through HostDelivery: the unit, not the controller, owns the guardian -------------------
@posix_only
@needs_profile
def test_the_controller_starts_only_the_unit_and_the_sealed_runtime_reports_itself(tmp_path, source):
    system = system_for(tmp_path, source)
    target, unit = system["target"], system["unit"]
    try:
        results = advance(system, ACTIVE)
        assert results[-1]["stage"] == ACTIVE, trail(results)
        receipt = read(state(target, RECEIPT_FILE))
        assert receipt["revision"] == source["a"] and receipt["runtime_root"].endswith(source["a"])
        # The controller asked systemd to show/start exactly its unit; it never spawned, stopped or killed.
        assert {argv[1] for argv in unit.calls} <= {"show", "start"} and unit.starts == 1
        request = validate_launch_request(read(state(target, LAUNCH_REQUEST_FILE)))
        assert request["descriptor_sha256"] == descriptor_digest(read(state(target, DESCRIPTOR_FILE)))
        launch = read(state(target, STATE_FILE))
        assert launch["pid"] == unit.process.pid and launch["invocation_id"] == unit.invocation
        assert read(state(target, TARGET_FILE)) == owner_target(target)
        journal = [json.loads(line) for line in state(target, SUPERVISOR_JOURNAL).read_text().splitlines()]
        assert [e["event"] for e in journal] == ["launch"] and journal[0]["invocation_id"] == unit.invocation
        await_work(system["host"], target, "idle")
    finally:
        finish(system)


@posix_only
@needs_profile
def test_a_restarted_controller_recognizes_the_running_unit_and_never_starts_a_second_fleet(tmp_path, source):
    system = system_for(tmp_path, source)
    target, unit = system["target"], system["unit"]
    try:
        assert advance(system, ACTIVE)[-1]["stage"] == ACTIVE
        first = read(state(target, RECEIPT_FILE))
        # LABELLED: the delivery controller restarts (new process objects, same durable state and unit).
        restarted = SystemdManagedFleetTarget(workload="fixture", fleet=fixture_fleet(), runner=unit)
        desc = read(state(target, DESCRIPTOR_FILE))
        again = restarted.start(target, desc)
        assert again["started"] is False and again["recovered"] is True and again["instance_id"] == first["instance_id"]
        assert restarted.running(target) is True and unit.starts == 1
        # A replayed start request to systemd for an active unit is a no-op, never a second runner.
        unit(["systemctl", "start", UNIT])
        assert unit.starts == 1 and read(state(target, RECEIPT_FILE))["instance_id"] == first["instance_id"]
    finally:
        finish(system)


@posix_only
@needs_profile
def test_a_failed_unit_restarts_under_the_same_checks_and_a_requested_stop_is_never_restarted(tmp_path, source):
    system = system_for(tmp_path, source)
    target, unit = system["target"], system["unit"]
    try:
        assert advance(system, ACTIVE)[-1]["stage"] == ACTIVE
        first = read(state(target, RECEIPT_FILE))
        await_work(system["host"], target, "idle")
        # LABELLED injected crash of the unit's main process: the unit fails and its cgroup is emptied.
        unit.crash()
        assert not unit.active() and unit.process.returncode != 0 and not _alive(first["pid"])
        unit.restart_after_failure()
        deadline = time.monotonic() + 30
        while read(state(target, RECEIPT_FILE))["instance_id"] == first["instance_id"] and time.monotonic() < deadline:
            time.sleep(0.05)
        second = read(state(target, RECEIPT_FILE))
        # Exactly one runner again, the same sealed runtime, a new instance identity.
        assert second["instance_id"] != first["instance_id"] and second["revision"] == first["revision"]
        assert unit.starts == 2 and not _alive(first["pid"])
        journal = [json.loads(line)["event"] for line in state(target, SUPERVISOR_JOURNAL).read_text().splitlines()]
        assert journal == ["launch", "launch"]
        # A stop that the managed target requested is final: a restart of the unit starts nothing.
        await_work(system["host"], target, "idle")
        assert system["host"].stop(target)["stopped"] is True and not unit.active()
        unit.process.returncode = 1       # LABELLED: pretend systemd saw a failure and restarts anyway
        unit.restart_after_failure()
        assert unit.process.wait(timeout=30) == 2
        events = [json.loads(line) for line in state(target, SUPERVISOR_JOURNAL).read_text().splitlines()]
        assert events[-1] == {**events[-1], "event": "refused", "reason_code": "stop_requested"}
    finally:
        finish(system)


@posix_only
@needs_profile
def test_a_restart_whose_old_child_survived_refuses_instead_of_running_a_second_fleet(tmp_path, source):
    system = system_for(tmp_path, source)
    target, unit = system["target"], system["unit"]
    try:
        assert advance(system, ACTIVE)[-1]["stage"] == ACTIVE
        first = read(state(target, RECEIPT_FILE))
        survivor = unit.crash(cgroup_cleanup=False)   # LABELLED: the old sealed child outlives its unit
        assert survivor == first["pid"] and _alive(survivor)
        unit.restart_after_failure()
        assert unit.process.wait(timeout=30) == 2 and unit.starts == 2
        events = [json.loads(line) for line in state(target, SUPERVISOR_JOURNAL).read_text().splitlines()]
        assert events[-1]["event"] == "refused" and events[-1]["reason_code"] == "previous_instance_alive"
        assert read(state(target, RECEIPT_FILE))["instance_id"] == first["instance_id"], "no second instance"
    finally:
        receipt = read(state(target, RECEIPT_FILE))
        if _alive(receipt.get("pid")):
            os.killpg(receipt["pid"], signal.SIGKILL)
        finish(system)


@posix_only
@needs_profile
def test_a_failed_candidate_rolls_back_to_the_predecessor_through_the_same_unit(tmp_path, source):
    system = system_for(tmp_path, source)
    target, unit = system["target"], system["unit"]
    try:
        assert advance(system, ACTIVE)[-1]["stage"] == ACTIVE
        good = read(state(target, DESCRIPTOR_FILE))
        await_work(system["host"], target, "idle")
        release = reviewed_release(system["store"], system["org"],
                                   record_candidate={**candidate(), "base": system["delivery"].github.main,
                                                     "revision": "5" * 40, "branch": "harness/two",
                                                     "task_id": "two"})
        plan = plan_document(release, plan_id="managed-plan-2", target_id=TARGET_ID, expected=descriptor_digest(good),
                             image=runtime_image(source["root"]), profile=PROFILE, canary=CANARY_FLEET,
                             descriptor_revision=source["b"], consumption_timeout=900)
        system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
        results = advance(system, ROLLED_BACK)
        assert results[-1]["stage"] == ROLLED_BACK, trail(results)
        restored = read(state(target, RECEIPT_FILE))
        assert restored["revision"] == source["a"] and read(state(target, DESCRIPTOR_FILE)) == good
        # Forward start, candidate start, predecessor restart: each only `systemctl start`, never stop/kill.
        assert unit.starts == 3 and {argv[1] for argv in unit.calls} <= {"show", "start"}
        with system["store"].transaction() as tx:
            assert tx.get(BUCKET_INTENTS, "managed-plan-2")["rollback"]["verified"] is True
    finally:
        finish(system)


# ----- supervise: every (re)start re-validates what the controller persisted -------------------------------
def persisted(tmp_path, source, host):
    """A sealed runtime, the descriptor, the target snapshot and the launch request, as `_launch` writes
    them, but without starting anything."""
    document, target = systemd_target(tmp_path, source["root"])
    desc = descriptor(target, source["root"], source["a"])
    host.materialize(target, desc)
    host.switch(target, desc, expected=None)
    manifest = host.verify(target, desc)
    Path(target["state_dir"]).mkdir(parents=True, exist_ok=True)
    (Path(target["state_dir"]) / TARGET_FILE).write_text(json.dumps(owner_target(target)), encoding="utf-8")
    from codex_harness.domain.managed_runtime import manifest_digest
    request = {"schema": "urn:zeus:managed-launch-request:1", "target_id": target["target_id"],
               "descriptor_sha256": descriptor_digest(desc), "manifest_sha256": manifest_digest(manifest),
               "workload": "fixture", "requested_at": "2026-09-25T00:00:00+00:00"}
    (Path(target["state_dir"]) / LAUNCH_REQUEST_FILE).write_text(json.dumps(request), encoding="utf-8")
    return target, desc, request


SETTLED = {"paused": True, "settled": True}


@posix_only
@pytest.mark.parametrize("fault, code", [
    ("no_request", "launch_request_invalid"), ("foreign_request", "launch_request_foreign"),
    ("changed_descriptor", "descriptor_changed"), ("changed_manifest", "runtime_manifest_changed"),
    ("stop_requested", "stop_requested"), ("debt_held", "fleet_debt_held"), ("debt_unknown", "fleet_debt_unknown"),
    ("gate_down", "fleet_pause_unknown"), ("wrong_kind", "launch_request_foreign")])
def test_supervise_refuses_before_any_launch_and_names_why(tmp_path, source, fault, code):
    host = SystemdManagedFleetTarget(workload="fixture", fleet=fixture_fleet(), runner=None)
    target, desc, request = persisted(tmp_path, source, host)
    root = Path(target["state_dir"])
    gate = lambda target_id, digest: SETTLED  # noqa: E731
    if fault == "no_request":
        (root / LAUNCH_REQUEST_FILE).unlink()
    elif fault == "foreign_request":
        (root / LAUNCH_REQUEST_FILE).write_text(json.dumps({**request, "target_id": "other"}), encoding="utf-8")
    elif fault == "changed_descriptor":
        (root / LAUNCH_REQUEST_FILE).write_text(json.dumps({**request, "descriptor_sha256": "0" * 64}),
                                                encoding="utf-8")
    elif fault == "changed_manifest":
        (root / LAUNCH_REQUEST_FILE).write_text(json.dumps({**request, "manifest_sha256": "0" * 64}),
                                                encoding="utf-8")
    elif fault == "stop_requested":
        (root / "stop.json").write_text("{}", encoding="utf-8")
    elif fault == "debt_held":
        gate = lambda target_id, digest: {"paused": True, "settled": False}  # noqa: E731
    elif fault == "debt_unknown":
        gate = lambda target_id, digest: {"paused": True, "settled": False, "reason_code": "debt_unknown"}  # noqa: E731
    elif fault == "gate_down":
        def gate(target_id, digest):
            raise ConnectionError("labelled injected unreachable Fleet store")
    elif fault == "wrong_kind":
        (root / TARGET_FILE).write_text(json.dumps({**owner_target(target), "kind": "managed_fleet"}),
                                        encoding="utf-8")
    launched = []
    assert supervise(str(root), gate=gate, launcher=lambda *args: launched.append(args) or 0) == 2
    assert launched == []
    events = [json.loads(line) for line in (root / SUPERVISOR_JOURNAL).read_text().splitlines()]
    assert events[-1]["event"] == "refused" and events[-1]["reason_code"] == code


@posix_only
def test_supervise_launches_exactly_the_persisted_request_once_the_checks_hold(tmp_path, source):
    host = SystemdManagedFleetTarget(workload="fixture", fleet=fixture_fleet(), runner=None)
    target, desc, request = persisted(tmp_path, source, host)
    launched, gates = [], []
    code = supervise(target["state_dir"], gate=lambda t, d: gates.append((t, d)) or SETTLED,
                     launcher=lambda *args: launched.append(args) or 0)
    assert code == 0 and gates == [(target["target_id"], request["descriptor_sha256"])]
    assert launched == [(str(Path(target["state_dir"])), request["descriptor_sha256"], "fixture")]


@posix_only
def test_the_unit_state_is_read_never_guessed(tmp_path, source):
    _, target = systemd_target(tmp_path, source["root"])

    def unknown(argv, timeout=None):
        return subprocess.CompletedProcess(argv, 0, "ActiveState=maintenance\n", "")

    def broken(argv, timeout=None):
        return subprocess.CompletedProcess(argv, 1, "", "Failed to connect to bus")

    for runner in (unknown, broken):
        with pytest.raises(RuntimeError):
            SystemdManagedFleetTarget(fleet=fixture_fleet(), runner=runner).unit_active(target)
